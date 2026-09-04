/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "lwip.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "lwip/netif.h"
#include "lwip/ip4_addr.h"
#include "lwip/apps/mqtt.h"
#include "mcp2515.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* DUAL_CORE_BOOT_SYNC_SEQUENCE: Define for dual core boot synchronization    */
/*                             demonstration code based on hardware semaphore */
/* This define is present in both CM7/CM4 projects                            */
/* To comment when developping/debugging on a single core                     */
#define DUAL_CORE_BOOT_SYNC_SEQUENCE

#if defined(DUAL_CORE_BOOT_SYNC_SEQUENCE)
#ifndef HSEM_ID_0
#define HSEM_ID_0 (0U) /* HW semaphore 0*/
#endif
#endif /* DUAL_CORE_BOOT_SYNC_SEQUENCE */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

COM_InitTypeDef BspCOMInit;

SPI_HandleTypeDef hspi1;

/* USER CODE BEGIN PV */
CAN_Frame rxFrame;
CAN_Frame txFrame;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* ==========================================================================
 * MQTT CLIENT — connects to the same broker the Python GUI uses
 * (gtw_mqtt_commands.py: BROKER = "192.168.1.10", PORT = 1883).
 *
 * The GUI PUBLISHES commands on:
 *   tbm/EMERGENCY_STOP, tbm/startup_procedure, tbm/operation_mode,
 *   tbm/mobility, tbm/cutterhead, tbm/conveyer, stm32/led
 * and a one-shot handshake request on tbm/handshake (sent once on GUI
 * boot, and again on every MQTT reconnect) - see below.
 * and SUBSCRIBES to stm32/# to receive feedback/telemetry back.
 *
 * So this firmware subscribes to "tbm/#" and "stm32/#" to receive every
 * command the GUI sends, and prints each one to UART as it arrives.
 * ==========================================================================*/

#define MQTT_BROKER_IP0   192
#define MQTT_BROKER_IP1   168
#define MQTT_BROKER_IP2   1
#define MQTT_BROKER_IP3   10
#define MQTT_BROKER_PORT  1883
#define MQTT_CLIENT_ID    "STM32_TBM_GATEWAY"

/* ==========================================================================
 * HANDSHAKE — proves an actual round trip, not just "broker connection
 * succeeded". GUI sends TOPIC_HANDSHAKE_REQ once per (re)connect; this
 * firmware replies on TOPIC_HANDSHAKE_ACK, which the GUI uses to light
 * its "TBM Ready" indicator only once this specific reply is seen.
 * ==========================================================================*/
#define TOPIC_HANDSHAKE_REQ   "tbm/handshake"
#define TOPIC_HANDSHAKE_ACK   "stm32/handshake_ack"

/* ==========================================================================
 * HEARTBEAT — ongoing 5s deadman's switch, separate from the one-shot
 * handshake above. GUI pings TOPIC_HEARTBEAT_REQ every 5s; this firmware
 * replies instantly on TOPIC_HEARTBEAT_ACK AND resets its own watchdog
 * timer. If this firmware doesn't see a fresh ping within HEARTBEAT_TIMEOUT_MS
 * (2 missed beats), it independently broadcasts a real EMERGENCY_STOP CAN
 * frame and latches into a fault state - cleared only by the GUI's RESUME
 * button sending "CLEAR EMERGENCY" on tbm/EMERGENCY_STOP (the same command
 * that already clears a manually-triggered E-STOP, reused here for
 * consistency rather than inventing a second reset mechanism).
 * ==========================================================================*/
#define TOPIC_HEARTBEAT_REQ     "tbm/heartbeat"
#define TOPIC_HEARTBEAT_ACK     "stm32/heartbeat_ack"
#define HEARTBEAT_TIMEOUT_MS    10500   /* trips on the 2nd missed beat (GUI pings
                                          * every 5s) - 10500 rather than exactly
                                          * 10000 gives a small jitter allowance
                                          * so a single slightly-late packet
                                          * doesn't false-trigger it */

static uint32_t last_heartbeat_rx_tick = 0;
static uint8_t  heartbeat_fault        = 0;   /* latched - only CLEAR EMERGENCY resets it */
static uint8_t  estop_fault_led        = 0;   /* separate from heartbeat_fault - drives the
                                                * distinct sequential strobe pattern below,
                                                * so an operator-triggered E-STOP looks
                                                * visually different from a lost heartbeat */
static uint8_t  heartbeat_grace_active = 1;   /* true until the first ping ever arrives,
                                                * so the watchdog doesn't trip before the
                                                * GUI has even had a chance to connect */

static mqtt_client_t *mqtt_client;
static uint8_t mqtt_connect_pending = 0;   /* set once netif is up, cleared once connect() called */

/* Holds the topic name for the publish currently streaming in — lwIP's
 * MQTT client delivers topic and payload via two separate callbacks, and
 * payload may arrive in multiple fragments for larger messages. */
static char     mqtt_incoming_topic[128];
static char     mqtt_incoming_payload[512];
static uint16_t mqtt_incoming_payload_len;

/* ==========================================================================
 * MQTT <-> CAN GENERIC RELAY
 *
 * The command dictionary (what each GUI action means, and which CAN
 * ID/data it maps to) now lives entirely on the PC side, in
 * gtw_mqtt_commands.py's CAN_COMMANDS table. This firmware no longer
 * interprets anything - it just relays raw CAN frames in both directions:
 *
 *   PC  -> TOPIC_CAN_TX -> this firmware parses the frame and transmits
 *          it verbatim onto the CAN bus (no lookup table, no
 *          interpretation - just extract ID/ext/rtr/dlc/data and send).
 *
 *   CAN bus -> this firmware -> TOPIC_CAN_RX -> PC, for every single
 *          frame received, so the PC can see what other boards are
 *          reporting without the STM needing to know what any of it means.
 *
 * Wire format (plain text, easy to read/debug via any MQTT client):
 *   "<hex_id>,<ext 0/1>,<rtr 0/1>,<dlc>,<hex_data>"
 * e.g. "10,0,0,1,01" = ID 0x010, standard, data frame, DLC 1, data byte 01
 *
 * "stm32/led" stays handled separately below (mqtt_handle_led_command) -
 * that one controls this board's own onboard LEDs directly, not a CAN
 * device, so it doesn't go through this relay.
 * ==========================================================================*/
#define TOPIC_CAN_TX   "tbm/can_tx"
#define TOPIC_CAN_RX   "stm32/can_rx"

/* Parses a TOPIC_CAN_TX payload into a CAN_Frame. Returns 1 on success,
 * 0 if the payload didn't parse (malformed - logged and dropped rather
 * than risking transmitting garbage onto the bus). */
static uint8_t parse_can_tx_payload(const char *payload, CAN_Frame *frame)
{
    unsigned int id = 0, ext = 0, rtr = 0, dlc = 0;
    char hexdata[17] = { 0 };   /* up to 8 bytes = 16 hex chars + null */

    int n = sscanf(payload, "%x,%u,%u,%u,%16s", &id, &ext, &rtr, &dlc, hexdata);
    if (n < 4)
    {
        return 0;   /* need at least id/ext/rtr/dlc - hexdata is optional if dlc==0 */
    }

    if (dlc > 8) dlc = 8;

    frame->id  = id;
    frame->ext = (ext != 0) ? 1 : 0;
    frame->rtr = (rtr != 0) ? 1 : 0;
    frame->dlc = (uint8_t)dlc;
    memset(frame->data, 0, sizeof(frame->data));

    size_t hexlen = strlen(hexdata);
    for (uint8_t i = 0; i < dlc; i++)
    {
        if (hexlen < (size_t)(i * 2 + 2))
        {
            break;   /* fewer data bytes arrived than DLC claimed - leave rest as 0 */
        }
        char byte_str[3] = { hexdata[i * 2], hexdata[i * 2 + 1], '\0' };
        frame->data[i] = (uint8_t)strtol(byte_str, NULL, 16);
    }

    return 1;
}

/* Fired when a TOPIC_CAN_RX publish completes (success/fail) */
static void mqtt_can_rx_pub_cb(void *arg, err_t result)
{
    (void)arg;
    if (result != ERR_OK)
    {
        printf("MQTT: CAN RX relay publish failed, err=%d\r\n", (int)result);
    }
}

/* Encodes a received CAN frame in the same wire format and relays it to
 * the PC over TOPIC_CAN_RX - called for every frame this board receives
 * off the bus, regardless of what it means (the PC decides that). */
static void mqtt_publish_can_rx(CAN_Frame *frame)
{
    if (mqtt_client == NULL)
    {
        return;   /* not connected yet - nothing to relay to */
    }

    char hexdata[17] = { 0 };
    for (uint8_t i = 0; i < frame->dlc && i < 8; i++)
    {
        sprintf(&hexdata[i * 2], "%02X", frame->data[i]);
    }

    char payload[64];
    int len = snprintf(payload, sizeof(payload), "%lX,%u,%u,%u,%s",
                        (unsigned long)frame->id, frame->ext, frame->rtr,
                        frame->dlc, hexdata);
    if (len < 0) return;

    err_t err = mqtt_publish(mqtt_client, TOPIC_CAN_RX, payload, (u16_t)len,
                              0 /* qos */, 0 /* retain */,
                              mqtt_can_rx_pub_cb, NULL);
    if (err != ERR_OK)
    {
        printf("MQTT: CAN RX relay publish call failed, err=%d\r\n", (int)err);
    }
}

/* Drives the board's physical LD1 (green) / LD2 (yellow) / LD3 (red) LEDs
 * based on an "stm32/led" command from the GUI. Treats them as a single
 * mutually-exclusive indicator — turning one on turns the other two off —
 * since that's the simplest mapping for "which LED is currently commanded".
 * If your team wants independent on/off control of each LED instead
 * (rather than one-at-a-time), this is the function to change: just drop
 * the "turn the others off" lines and add explicit ON/OFF payload variants
 * to the table (e.g. "YELLOW LED ON" / "YELLOW LED OFF"). */
static void mqtt_handle_led_command(const char *payload)
{
    if (strcmp(payload, "GREEN LED") == 0)
    {
        BSP_LED_On(LED_GREEN);
        BSP_LED_Off(LED_YELLOW);
        BSP_LED_Off(LED_RED);
        printf("  physical LED -> GREEN on\r\n");
    }
    else if (strcmp(payload, "YELLOW LED") == 0)
    {
        BSP_LED_On(LED_YELLOW);
        BSP_LED_Off(LED_GREEN);
        BSP_LED_Off(LED_RED);
        printf("  physical LED -> YELLOW on\r\n");
    }
    else if (strcmp(payload, "RED LED") == 0)
    {
        BSP_LED_On(LED_RED);
        BSP_LED_Off(LED_GREEN);
        BSP_LED_Off(LED_YELLOW);
        printf("  physical LED -> RED on\r\n");
    }
}

/* Fired when the handshake ACK publish completes (success/fail) */
static void mqtt_handshake_pub_cb(void *arg, err_t result)
{
    (void)arg;
    if (result != ERR_OK)
    {
        printf("MQTT: handshake ACK publish failed, err=%d\r\n", (int)result);
    }
}

/* Sends the handshake ACK back to the GUI - QOS0, no retain, fire and
 * forget (the GUI will simply re-send its handshake request on its own
 * timeout/retry logic if this doesn't get through). */
static void mqtt_send_handshake_ack(void)
{
    err_t err = mqtt_publish(mqtt_client, TOPIC_HANDSHAKE_ACK, "ACK", 3,
                              0 /* qos */, 0 /* retain */,
                              mqtt_handshake_pub_cb, NULL);
    if (err != ERR_OK)
    {
        printf("MQTT: handshake ACK publish call failed, err=%d\r\n", (int)err);
    }
    else
    {
        printf("MQTT: handshake ACK sent -> %s\r\n", TOPIC_HANDSHAKE_ACK);
    }
}

/* Fired when the heartbeat ACK publish completes (success/fail) */
static void mqtt_heartbeat_pub_cb(void *arg, err_t result)
{
    (void)arg;
    if (result != ERR_OK)
    {
        printf("MQTT: heartbeat ACK publish failed, err=%d\r\n", (int)result);
    }
}

/* Sends the heartbeat ACK back to the GUI - same fire-and-forget approach
 * as the handshake ACK. Called every time a fresh ping arrives. */
static void mqtt_send_heartbeat_ack(void)
{
    err_t err = mqtt_publish(mqtt_client, TOPIC_HEARTBEAT_ACK, "PONG", 4,
                              0 /* qos */, 0 /* retain */,
                              mqtt_heartbeat_pub_cb, NULL);
    if (err != ERR_OK)
    {
        printf("MQTT: heartbeat ACK publish call failed, err=%d\r\n", (int)err);
    }
}

/* Broadcasts a real EMERGENCY_STOP CAN frame - the same ID/command byte
 * (0x010 / 0x01) the GUI's own CAN_COMMANDS dictionary uses for a manually
 * triggered EMERGENCY_STOP, so downstream CAN nodes don't need to know
 * this came from the watchdog rather than an operator press - it's the
 * identical safety signal either way. */
static void heartbeat_broadcast_emergency_stop(void)
{
    CAN_Frame frame = { 0 };
    frame.id  = 0x010;
    frame.ext = 0;
    frame.rtr = 0;
    frame.dlc = 1;
    frame.data[0] = 0x01;

    if (MCP2515_SendMessage(&frame) == HAL_OK)
    {
        printf("CAN TX (heartbeat watchdog) -> ID=0x010 DLC=1 Data: 01 (EMERGENCY_STOP)\r\n");
    }
    else
    {
        printf("CAN TX (heartbeat watchdog) FAILED\r\n");
    }
}

/* Called once per incoming PUBLISH, before any data arrives — gives us the
 * topic name and total payload length. */
static void mqtt_incoming_publish_cb(void *arg, const char *topic, u32_t tot_len)
{
    (void)arg;
    strncpy(mqtt_incoming_topic, topic, sizeof(mqtt_incoming_topic) - 1);
    mqtt_incoming_topic[sizeof(mqtt_incoming_topic) - 1] = '\0';
    mqtt_incoming_payload_len = 0;
    (void)tot_len;
}

/* Called with payload data as it arrives — may fire multiple times per
 * message. MQTT_DATA_FLAG_LAST marks the final fragment, at which point
 * we print the complete topic + payload to UART and bridge it onto CAN. */
static void mqtt_incoming_data_cb(void *arg, const u8_t *data, u16_t len, u8_t flags)
{
    (void)arg;
    uint16_t space_left = sizeof(mqtt_incoming_payload) - 1 - mqtt_incoming_payload_len;
    uint16_t copy_len = (len < space_left) ? len : space_left;

    memcpy(&mqtt_incoming_payload[mqtt_incoming_payload_len], data, copy_len);
    mqtt_incoming_payload_len += copy_len;
    mqtt_incoming_payload[mqtt_incoming_payload_len] = '\0';

    if (flags & MQTT_DATA_FLAG_LAST)
    {
        printf("MQTT RX -> %s | %s\r\n", mqtt_incoming_topic, mqtt_incoming_payload);

        /* Handshake request - reply with ACK and stop here, this isn't a
         * CAN-bridge command and shouldn't fall through to that logic. */
        if (strcmp(mqtt_incoming_topic, TOPIC_HANDSHAKE_REQ) == 0)
        {
            printf("MQTT: handshake request received - replying with ACK\r\n");
            mqtt_send_handshake_ack();
            mqtt_incoming_payload_len = 0;
            return;
        }

        /* Heartbeat ping - reply immediately, reset the watchdog timer, and
         * clear the initial grace period flag (first real ping means the
         * GUI is genuinely connected and pinging now). Also doesn't fall
         * through to the CAN-bridge logic below - this isn't a CAN command. */
        if (strcmp(mqtt_incoming_topic, TOPIC_HEARTBEAT_REQ) == 0)
        {
            last_heartbeat_rx_tick = HAL_GetTick();
            heartbeat_grace_active = 0;
            mqtt_send_heartbeat_ack();
            mqtt_incoming_payload_len = 0;
            return;
        }

        if (strcmp(mqtt_incoming_topic, "stm32/led") == 0)
        {
            mqtt_handle_led_command(mqtt_incoming_payload);
            mqtt_incoming_payload_len = 0;
            return;   /* onboard LED control, not a CAN frame - stop here */
        }

        /* Generic CAN relay - the only thing this firmware still does with
         * incoming MQTT commands. The GUI's CAN_COMMANDS dictionary (in
         * gtw_mqtt_commands.py) already decided exactly what CAN ID/data
         * this action means; we just parse and transmit it verbatim. */
        if (strcmp(mqtt_incoming_topic, TOPIC_CAN_TX) == 0)
        {
            CAN_Frame relayFrame;
            if (!parse_can_tx_payload(mqtt_incoming_payload, &relayFrame))
            {
                printf("MQTT: malformed tbm/can_tx payload, dropped: %s\r\n",
                       mqtt_incoming_payload);
                mqtt_incoming_payload_len = 0;
                return;
            }

            /* Inspecting the actual safety CAN frame content being relayed
             * (ID 0x010) rather than any topic/payload string - this
             * firmware no longer interprets those for anything else, so
             * this is the one place safety-relevant frames still get a
             * second look on their way through. */
            if (relayFrame.id == 0x010 && relayFrame.dlc >= 1)
            {
                if (relayFrame.data[0] == 0x01)   /* EMERGENCY_STOP */
                {
                    if (!estop_fault_led)
                    {
                        printf("E-STOP triggered from GUI - starting sequential LED strobe\r\n");
                    }
                    estop_fault_led = 1;
                }
                else if (relayFrame.data[0] == 0x03)   /* CLEAR EMERGENCY - the RESUME
                                                         * button's action, clears BOTH
                                                         * fault types together */
                {
                    if (heartbeat_fault || estop_fault_led)
                    {
                        printf("Emergency/heartbeat fault cleared by RESUME command\r\n");
                        BSP_LED_Off(LED_GREEN);
                        BSP_LED_Off(LED_YELLOW);
                        BSP_LED_Off(LED_RED);
                    }
                    heartbeat_fault = 0;
                    estop_fault_led = 0;
                    last_heartbeat_rx_tick = HAL_GetTick();
                }
            }

            if (MCP2515_SendMessage(&relayFrame) == HAL_OK)
            {
                printf("CAN TX (relay) -> ID=0x%lX DLC=%d Data:", relayFrame.id, relayFrame.dlc);
                for (uint8_t i = 0; i < relayFrame.dlc; i++)
                {
                    printf(" %02X", relayFrame.data[i]);
                }
                printf("\r\n");
            }
            else
            {
                printf("CAN TX (relay) FAILED\r\n");
            }
        }

        mqtt_incoming_payload_len = 0;
    }
}

/* Fired when a subscribe request completes (success/fail) */
static void mqtt_sub_request_cb(void *arg, err_t result)
{
    const char *topic = (const char *)arg;
    if (result == ERR_OK)
    {
        printf("MQTT: subscribed to %s\r\n", topic);
    }
    else
    {
        printf("MQTT: subscribe to %s FAILED (err=%d)\r\n", topic, (int)result);
    }
}

/* Fired on connect/disconnect */
static void mqtt_connection_cb(mqtt_client_t *client, void *arg, mqtt_connection_status_t status)
{
    (void)arg;
    if (status == MQTT_CONNECT_ACCEPTED)
    {
        printf("MQTT: connected to broker\r\n");

        /* Fresh grace period - the GUI's first heartbeat ping might take a
         * moment to arrive after the connection itself completes, and we
         * don't want the watchdog considering that a fault. */
        last_heartbeat_rx_tick = HAL_GetTick();
        heartbeat_grace_active = 1;

        err_t err;
        err = mqtt_subscribe(client, "tbm/#", 0, mqtt_sub_request_cb, (void *)"tbm/#");
        if (err != ERR_OK)
        {
            printf("MQTT: mqtt_subscribe(tbm/#) call failed, err=%d\r\n", (int)err);
        }

        err = mqtt_subscribe(client, "stm32/#", 0, mqtt_sub_request_cb, (void *)"stm32/#");
        if (err != ERR_OK)
        {
            printf("MQTT: mqtt_subscribe(stm32/#) call failed, err=%d\r\n", (int)err);
        }
    }
    else
    {
        printf("MQTT: disconnected/connect failed (status=%d) - will retry\r\n", (int)status);
        /* Allow the main loop to attempt reconnection */
        mqtt_connect_pending = 1;
    }
}

/* Kick off (or retry) the MQTT connection. Safe to call repeatedly —
 * mqtt_client_connect() is a no-op if already connected/connecting. */
static void mqtt_try_connect(void)
{
    if (mqtt_client == NULL)
    {
        mqtt_client = mqtt_client_new();
        if (mqtt_client == NULL)
        {
            printf("MQTT: mqtt_client_new() failed\r\n");
            return;
        }
        mqtt_set_inpub_callback(mqtt_client,
                                 mqtt_incoming_publish_cb,
                                 mqtt_incoming_data_cb,
                                 NULL);
    }

    ip_addr_t broker_ip;
    IP4_ADDR(&broker_ip, MQTT_BROKER_IP0, MQTT_BROKER_IP1, MQTT_BROKER_IP2, MQTT_BROKER_IP3);

    struct mqtt_connect_client_info_t ci;
    memset(&ci, 0, sizeof(ci));
    ci.client_id = MQTT_CLIENT_ID;

    printf("MQTT: connecting to %d.%d.%d.%d:%d...\r\n",
           MQTT_BROKER_IP0, MQTT_BROKER_IP1, MQTT_BROKER_IP2, MQTT_BROKER_IP3, MQTT_BROKER_PORT);

    err_t err = mqtt_client_connect(mqtt_client, &broker_ip, MQTT_BROKER_PORT,
                                     mqtt_connection_cb, NULL, &ci);
    if (err != ERR_OK)
    {
        printf("MQTT: mqtt_client_connect() call failed, err=%d - will retry\r\n", (int)err);
        mqtt_connect_pending = 1;
    }
    else
    {
        mqtt_connect_pending = 0;
    }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */
/* USER CODE BEGIN Boot_Mode_Sequence_0 */
#if defined(DUAL_CORE_BOOT_SYNC_SEQUENCE)
  int32_t timeout;
#endif /* DUAL_CORE_BOOT_SYNC_SEQUENCE */
/* USER CODE END Boot_Mode_Sequence_0 */

/* USER CODE BEGIN Boot_Mode_Sequence_1 */
#if defined(DUAL_CORE_BOOT_SYNC_SEQUENCE)
  /* Wait until CPU2 boots and enters in stop mode or timeout*/
  timeout = 0xFFFF;
  while((__HAL_RCC_GET_FLAG(RCC_FLAG_D2CKRDY) != RESET) && (timeout-- > 0));
  if ( timeout < 0 )
  {
  Error_Handler();
  }
#endif /* DUAL_CORE_BOOT_SYNC_SEQUENCE */
/* USER CODE END Boot_Mode_Sequence_1 */
  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();
/* USER CODE BEGIN Boot_Mode_Sequence_2 */
#if defined(DUAL_CORE_BOOT_SYNC_SEQUENCE)
/* When system initialization is finished, Cortex-M7 will release Cortex-M4 by means of
HSEM notification */
/*HW semaphore Clock enable*/
__HAL_RCC_HSEM_CLK_ENABLE();
/*Take HSEM */
HAL_HSEM_FastTake(HSEM_ID_0);
/*Release HSEM in order to notify the CPU2(CM4)*/
HAL_HSEM_Release(HSEM_ID_0,0);
/* wait until CPU2 wakes up from stop mode */
timeout = 0xFFFF;
while((__HAL_RCC_GET_FLAG(RCC_FLAG_D2CKRDY) == RESET) && (timeout-- > 0));
if ( timeout < 0 )
{
Error_Handler();
}
#endif /* DUAL_CORE_BOOT_SYNC_SEQUENCE */
/* USER CODE END Boot_Mode_Sequence_2 */

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_LWIP_Init();
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */

  /* USER CODE END 2 */

  /* Initialize leds */
  BSP_LED_Init(LED_GREEN);
  BSP_LED_Init(LED_YELLOW);
  BSP_LED_Init(LED_RED);

  /* Initialize USER push-button, will be used to trigger an interrupt each time it's pressed.*/
  BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);

  /* Initialize COM1 port (115200, 8 bits (7-bit data + 1 stop bit), no parity */
  BspCOMInit.BaudRate   = 115200;
  BspCOMInit.WordLength = COM_WORDLENGTH_8B;
  BspCOMInit.StopBits   = COM_STOPBITS_1;
  BspCOMInit.Parity     = COM_PARITY_NONE;
  BspCOMInit.HwFlowCtl  = COM_HWCONTROL_NONE;
  if (BSP_COM_Init(COM1, &BspCOMInit) != BSP_ERROR_NONE)
  {
    Error_Handler();
  }

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    MX_LWIP_Process();

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    extern struct netif gnetif;   /* declared in lwip.c, used below for MQTT connect gating */

    /* One-shot MCP2515 init + loopback self-test, run on the first loop
     * pass. Deliberately placed here rather than in USER CODE BEGIN 2:
     * this guarantees BSP_COM_Init() has already run, so printf() actually
     * reaches UART (USER CODE BEGIN 2 runs before BSP_COM_Init, where
     * prints would be silently lost). This marker also survives CubeMX
     * regeneration, unlike a custom marker name CubeMX doesn't recognize. */
    static uint8_t mcp2515_init_done = 0;
    if (!mcp2515_init_done)
    {
        mcp2515_init_done = 1;
        printf("Initializing MCP2515...\r\n");
        HAL_StatusTypeDef mcp_init_status = MCP2515_Init(&hspi1);


        if (mcp_init_status != HAL_OK)
        {
            printf("MCP2515 init FAILED - check SPI wiring/power\r\n");
            Error_Handler();
        }
        printf("MCP2515 init OK - Normal mode\r\n");

        printf("Running loopback self-test...\r\n");
        if (MCP2515_LoopbackSelfTest() == HAL_OK)
        {
            printf("LOOPBACK TEST: PASS - SPI link + MCP2515 driver working correctly\r\n");
        }
        else
        {
            printf("LOOPBACK TEST: FAIL - check wiring (SCK/MISO/MOSI/CS) and MCP2515 power\r\n");
        }

        printf("Ethernet: static IP 192.168.1.20 configured, waiting for link...\r\n");
    }

    /* Once the netif is up, connect to the MQTT broker. mqtt_connect_pending
     * starts at 0 so this only fires once naturally via the flag below being
     * primed on first pass, and again automatically if the connection drops
     * (mqtt_connection_cb sets mqtt_connect_pending = 1 on disconnect). */
    static uint8_t mqtt_first_attempt_done = 0;
    static uint32_t last_mqtt_attempt = 0;

    /* A raw physical cable unplug/replug doesn't reliably trigger lwIP's
     * MQTT disconnect callback (that normally relies on slower TCP-level
     * detection) - the client can be left thinking it's still connected
     * when it isn't. Watching the link state directly and forcing a clean
     * reconnect on every down->up transition catches this case, which the
     * connection-callback-only retry logic above didn't. */
    static uint8_t was_link_up = 0;
    uint8_t link_up_now = netif_is_link_up(&gnetif);
    if (link_up_now && !was_link_up)
    {
        printf("Ethernet link restored - forcing a fresh MQTT reconnect\r\n");
        if (mqtt_client != NULL)
        {
            mqtt_disconnect(mqtt_client);
        }
        mqtt_connect_pending = 1;
        last_mqtt_attempt = 0;   /* let the retry fire on the very next loop pass */
    }
    was_link_up = link_up_now;

    if (netif_is_up(&gnetif) && netif_is_link_up(&gnetif))
    {
        if (!mqtt_first_attempt_done)
        {
            mqtt_first_attempt_done = 1;
            mqtt_try_connect();
        }
        else if (mqtt_connect_pending && (HAL_GetTick() - last_mqtt_attempt >= 3000))
        {
            last_mqtt_attempt = HAL_GetTick();
            mqtt_try_connect();
        }
    }

    if (MCP2515_CheckReceive())
    {
        MCP2515_ReadMessage(&rxFrame);
        printf("CAN RX: ID=0x%lX  DLC=%d  Data:", rxFrame.id, rxFrame.dlc);
        for (uint8_t i = 0; i < rxFrame.dlc; i++)
        {
            printf(" %02X", rxFrame.data[i]);
        }
        printf("\r\n");

        /* Relay every received CAN frame back to the PC over Ethernet,
         * regardless of what it means - the GUI decides that based on ID,
         * this firmware just reports what showed up on the bus. */
        mqtt_publish_can_rx(&rxFrame);
    }

    /* Heartbeat watchdog - only checked once the grace period has ended
     * (i.e. at least one real ping has arrived since connecting), and only
     * trips once (heartbeat_fault latches, so this doesn't re-broadcast
     * EMERGENCY_STOP every single loop iteration while the fault persists -
     * only exactly once on the transition into fault). */
    if (!heartbeat_grace_active && !heartbeat_fault &&
        (HAL_GetTick() - last_heartbeat_rx_tick > HEARTBEAT_TIMEOUT_MS))
    {
        heartbeat_fault = 1;
        printf("HEARTBEAT LOST - no ping from GUI within %dms - broadcasting EMERGENCY_STOP\r\n",
               HEARTBEAT_TIMEOUT_MS);
        heartbeat_broadcast_emergency_stop();
    }

    /* Flash all three onboard LEDs together while the heartbeat fault is
     * active - a visible-from-across-the-room indicator that link
     * monitoring has tripped, independent of whatever the GUI's "stm32/led"
     * command last set. Non-blocking (HAL_GetTick()-based), so this
     * doesn't stall LWIP/MQTT/CAN processing elsewhere in the loop. Stops
     * automatically (LEDs turned off) the moment RESUME clears the fault
     * - see the CLEAR EMERGENCY handling above.
     *
     * A manually-triggered E-STOP gets a visually DIFFERENT pattern - a
     * one-by-one sequential strobe (GREEN -> YELLOW -> RED -> repeat) -
     * so it's immediately obvious which failure mode is active without
     * needing to check PuTTY. If both happen to be active at once,
     * heartbeat_fault takes priority (it implies a broader loss of link,
     * not just a manual stop), rather than trying to display both on the
     * same three physical LEDs simultaneously. */
    if (heartbeat_fault)
    {
        static uint32_t last_led_flash_tick = 0;
        static uint8_t  led_flash_on = 0;

        if (HAL_GetTick() - last_led_flash_tick >= 300)
        {
            last_led_flash_tick = HAL_GetTick();
            led_flash_on = !led_flash_on;

            if (led_flash_on)
            {
                BSP_LED_On(LED_GREEN);
                BSP_LED_On(LED_YELLOW);
                BSP_LED_On(LED_RED);
            }
            else
            {
                BSP_LED_Off(LED_GREEN);
                BSP_LED_Off(LED_YELLOW);
                BSP_LED_Off(LED_RED);
            }
        }
    }
    else if (estop_fault_led)
    {
        static uint32_t last_estop_strobe_tick = 0;
        static uint8_t  estop_strobe_step = 0;   /* 0=green, 1=yellow, 2=red */

        if (HAL_GetTick() - last_estop_strobe_tick >= 250)
        {
            last_estop_strobe_tick = HAL_GetTick();

            BSP_LED_Off(LED_GREEN);
            BSP_LED_Off(LED_YELLOW);
            BSP_LED_Off(LED_RED);

            switch (estop_strobe_step)
            {
                case 0: BSP_LED_On(LED_GREEN);  break;
                case 1: BSP_LED_On(LED_YELLOW); break;
                case 2: BSP_LED_On(LED_RED);    break;
            }
            estop_strobe_step = (estop_strobe_step + 1) % 3;
        }
    }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Supply configuration update enable
  */
  HAL_PWREx_ConfigSupply(PWR_DIRECT_SMPS_SUPPLY);

  /** Configure the main internal regulator output voltage
  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_DIV1;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 4;
  RCC_OscInitStruct.PLL.PLLN = 9;
  RCC_OscInitStruct.PLL.PLLP = 2;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;
  RCC_OscInitStruct.PLL.PLLRGE = RCC_PLL1VCIRANGE_3;
  RCC_OscInitStruct.PLL.PLLVCOSEL = RCC_PLL1VCOMEDIUM;
  RCC_OscInitStruct.PLL.PLLFRACN = 3072;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_D3PCLK1|RCC_CLOCKTYPE_D1PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_APB3_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV1;
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 0x0;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  hspi1.Init.NSSPolarity = SPI_NSS_POLARITY_LOW;
  hspi1.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
  hspi1.Init.TxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi1.Init.RxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi1.Init.MasterSSIdleness = SPI_MASTER_SS_IDLENESS_00CYCLE;
  hspi1.Init.MasterInterDataIdleness = SPI_MASTER_INTERDATA_IDLENESS_00CYCLE;
  hspi1.Init.MasterReceiverAutoSusp = SPI_MASTER_RX_AUTOSUSP_DISABLE;
  hspi1.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_DISABLE;
  hspi1.Init.IOSwap = SPI_IO_SWAP_DISABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(USB_OTG_FS_PWR_EN_GPIO_Port, USB_OTG_FS_PWR_EN_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(MCP2515_CS_GPIO_Port, MCP2515_CS_Pin, GPIO_PIN_SET);

  /*Configure GPIO pins : USB_OTG_FS_PWR_EN_Pin MCP2515_CS_Pin */
  GPIO_InitStruct.Pin = USB_OTG_FS_PWR_EN_Pin|MCP2515_CS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pin : MCP2515_INT_Pin */
  GPIO_InitStruct.Pin = MCP2515_INT_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_EVT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(MCP2515_INT_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : USB_OTG_FS_OVCR_Pin */
  GPIO_InitStruct.Pin = USB_OTG_FS_OVCR_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(USB_OTG_FS_OVCR_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : PA8 PA11 PA12 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_11|GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF10_OTG1_FS;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
