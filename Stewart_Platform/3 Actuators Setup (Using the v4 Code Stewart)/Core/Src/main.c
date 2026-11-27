/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Stewart platform - 4 actuator sync on NUCLEO-G431RB
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
  *
  * Pin map (must match the .ioc):
  *   Leg | Dir A | Dir B | PWM (TIM3, ARR 3399) | Encoder (65535)
  *   M1  | PA0   | PA4   | CH1 PB4              | TIM1 PC0/PC1
  *   M2  | PB0   | PA10  | CH2 PA7              | TIM2 PA15/PA1
  *   M3  | PB5   | PB10  | CH3 PC8              | TIM4 PB6/PA12
  *   M4  | PC2   | PC3   | CH4 PB1              | TIM8 PC6/PC7
  *   CAN : FDCAN1 RX PA11 / TX PB9, 125 kbit/s (prescaler 68, seg1 15, seg2 4)
  *   UART: USART2 PA2/PA3 (ST-LINK virtual COM), 115200
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
// --- Stewart platform state ---
typedef enum{
	SLEEP_STANDBY,
	FORWARD,
	BRAKE,
	BACKWARD,
	HOMING                 // open-loop retract to end stops (used to recover from a fault)
} stewart_state;

// --- command direction ---
typedef enum{
	GO,
	REVERSE
} command_direction;

// --- one actuator: H-bridge + encoder ---
typedef struct{
	// PWM (speed)
	TIM_HandleTypeDef *timer;
	uint32_t channel;
	// direction pins
	GPIO_TypeDef *gpioportA;
	uint16_t GPIOPinA;
	GPIO_TypeDef *gpioportB;
	uint16_t GPIOPinB;
	// encoder (timer in encoder mode, period 65535)
	TIM_HandleTypeDef *enc_timer;
	uint8_t enc_invert;          // set to 1 if this leg counts NEGATIVE while extending
	uint16_t enc_last;           // last raw 16-bit counter value
	int32_t position_ticks;      // signed position (+ extending)
	int32_t speed_ticks;         // ticks since last speed update (signed)
} motor;

// Result output format for findmin
typedef struct{
	uint32_t idx;
	uint32_t value;
} minResult;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define ACTUATOR_COUNT 3U       // 3 or 4: legs M1..M(ACTUATOR_COUNT) are used, the rest are ignored

// 1 = closed-loop position sync, 0 = open loop (every leg runs at BASE_DUTY, no sync, no fault stop)
#define SYNC_ENABLE 1

// 1 = start extending as soon as the board boots (no button press needed)
#define AUTO_START 0

// 1 = start FDCAN and send/receive frames, 0 = CAN completely off (no transceiver needed)
#define CAN_ENABLE 0

// --- Timing ---
#define CTRL_PERIOD_MS      10U     // encoder read + sync loop
#define PRINT_PERIOD_MS     100U    // UART print + speed window
#define CAN_PERIOD_MS       100U    // CAN status frames
#define BUTTON_DEBOUNCE_MS  200U

// --- Sync controller (tune these) ---
// Duties are a % of the PWM period, so they follow whatever ARR is set in CubeMX.
#define BASE_DUTY_PCT  82.0f    // nominal duty (headroom for the lagging legs)
#define DUTY_MIN_PCT   18.0f    // don't let a motor stall
#define DUTY_MAX_PCT   95.0f    // leaves PWM off-time for the driver's high side
#define I_LIMIT_PCT    23.5f    // max duty the I term can contribute (anti-windup)
#define KP          1.5f        // duty counts per tick of position error
#define KI          0.01f       // duty counts added per tick of error, every 10 ms
#define KD          0.0f        // leave at 0 to start (encoder ticks make D noisy)

// --- Safety ---
#define ERR_LIMIT   10000       // ticks: if any leg gets this far from the average, stop all

// --- UART transmit ring buffer (must be a power of two) ---
#define TX_BUF_SIZE 2048U

// --- CAN message IDs (standard 11-bit) ---
#define CAN_ID_STATUS   0x101U  // [0]=state [1]=fault [2]=counter
#define CAN_ID_POS_12   0x110U  // int32 position M1, int32 position M2 (little-endian)
#define CAN_ID_POS_34   0x111U  // int32 position M3, int32 position M4 (little-endian)
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

FDCAN_HandleTypeDef hfdcan1;

TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim4;
TIM_HandleTypeDef htim8;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */
// states/buttons
static stewart_state motor_state = SLEEP_STANDBY;
static volatile uint8_t button_event = 0U;

// motors: leg N = H-bridge N + encoder N (all PWM on TIM3)
static motor h_bridge[ACTUATOR_COUNT] = {
	{ // M1: PWM TIM3 CH1 (PB4), encoder TIM1 (PC0/PC1)
		.timer = &htim3, .channel = TIM_CHANNEL_1,
		.gpioportA = M1_A_GPIO_Port, .GPIOPinA = M1_A_Pin,
		.gpioportB = M1_B_GPIO_Port, .GPIOPinB = M1_B_Pin,
		.enc_timer = &htim1, .enc_invert = 0U
	},
	{ // M2: PWM TIM3 CH2 (PA7), encoder TIM2 (PA15/PA1)
		.timer = &htim3, .channel = TIM_CHANNEL_2,
		.gpioportA = M2_A_GPIO_Port, .GPIOPinA = M2_A_Pin,
		.gpioportB = M2_B_GPIO_Port, .GPIOPinB = M2_B_Pin,
		.enc_timer = &htim2, .enc_invert = 1U
	},
	{ // M3: PWM TIM3 CH3 (PC8), encoder TIM4 (PB6/PA12)
		.timer = &htim3, .channel = TIM_CHANNEL_3,
		.gpioportA = M3_A_GPIO_Port, .GPIOPinA = M3_A_Pin,
		.gpioportB = M3_B_GPIO_Port, .GPIOPinB = M3_B_Pin,
		.enc_timer = &htim4, .enc_invert = 0U
	},
#if ACTUATOR_COUNT > 3
	{ // M4: PWM TIM3 CH4 (PB1), encoder TIM8 (PC6/PC7)
		.timer = &htim3, .channel = TIM_CHANNEL_4,
		.gpioportA = M4_A_GPIO_Port, .GPIOPinA = M4_A_Pin,
		.gpioportB = M4_B_GPIO_Port, .GPIOPinB = M4_B_Pin,
		.enc_timer = &htim8, .enc_invert = 0U
	},
#endif
};

// Speeds array (magnitude of ticks per print window)
static volatile uint32_t speeds[ACTUATOR_COUNT];

// print / CAN timing
static uint32_t last_uart_print_ms = 0;
static uint32_t last_can_ms = 0;

// per-leg sync state (for printing / tuning)
static int32_t sync_error[ACTUATOR_COUNT];
static int32_t duty_cmd[ACTUATOR_COUNT];
static float   i_acc[ACTUATOR_COUNT];
static int32_t err_prev[ACTUATOR_COUNT];
static uint8_t fault = 0U;          // 1 = stopped because a leg got too far from the others

// duty limits in timer counts (computed from the PWM period at start-up)
static int32_t duty_base, duty_min, duty_max;
static float   i_limit;

// UART transmit ring buffer (filled by uart_write, drained by uart_pump)
static uint8_t  tx_buf[TX_BUF_SIZE];
static uint16_t tx_head = 0U;
static uint16_t tx_tail = 0U;

// CAN bookkeeping
static uint8_t  can_counter = 0U;
static uint32_t can_tx_count = 0U;
static uint32_t can_rx_count = 0U;
static uint32_t can_last_rx_id = 0U;
static uint8_t  can_last_rx_data[8];
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_FDCAN1_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM8_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM2_Init(void);
/* USER CODE BEGIN PFP */
static void duty_limits_init(void);
static void move_all_generic(command_direction direction);
static void motors_brake(void);
static void motors_sleep(void);
static minResult simple_findmin(const volatile uint32_t arr[], uint32_t length);
static void update_encoders(void);
static void sync_actuators(void);
static int32_t clamp_i32(int32_t x, int32_t lo, int32_t hi);
static void handle_button(void);
static void uart_write(const char *s, uint16_t n);
static void uart_pump(void);
static void print_status(const int32_t s[], minResult mn);
static void can_init(void);
static void can_send(uint32_t id, const uint8_t data[8]);
static void can_send_status(void);
static void can_poll_rx(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void duty_limits_init(void){
	// all legs share TIM3, so one ARR sets every duty limit
	uint32_t period = __HAL_TIM_GET_AUTORELOAD(&htim3) + 1U;
	duty_base = (int32_t)((float)period * BASE_DUTY_PCT / 100.0f);
	duty_min  = (int32_t)((float)period * DUTY_MIN_PCT  / 100.0f);
	duty_max  = (int32_t)((float)period * DUTY_MAX_PCT  / 100.0f);
	i_limit   = (float)period * I_LIMIT_PCT / 100.0f;
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		duty_cmd[i] = duty_base;
	}
}

static void move_all_generic(command_direction direction){
	// fresh PID state each move (err sign flips between extend and retract)
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		i_acc[i] = 0.0f;
		err_prev[i] = 0;
		sync_error[i] = 0;
		duty_cmd[i] = duty_base;
	}

	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];

		// every move starts all legs at the same duty; sync adjusts from there
		__HAL_TIM_SET_COMPARE(m->timer, m->channel, (uint32_t)duty_base);

		if (direction == GO){
			m->gpioportA->BSRR = (uint32_t)m->GPIOPinA;          // Set A
			m->gpioportB->BSRR = (uint32_t)m->GPIOPinB << 16U;   // Reset B
		}
		if (direction == REVERSE){
			m->gpioportA->BSRR = (uint32_t)m->GPIOPinA << 16U;   // Reset A
			m->gpioportB->BSRR = (uint32_t)m->GPIOPinB;          // Set B
		}
		HAL_TIM_PWM_Start(m->timer, m->channel);
	}
}

static void motors_sleep(void){
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];
		HAL_TIM_PWM_Stop(m->timer, m->channel);
	}
}

static void motors_brake(void){
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];
		m->gpioportA->BSRR = (uint32_t)m->GPIOPinA;   // Set A
		m->gpioportB->BSRR = (uint32_t)m->GPIOPinB;   // Set B
	}
}

static minResult simple_findmin(const volatile uint32_t arr[], uint32_t length){
	minResult min = {
		.idx = 0,
		.value = arr[0]
	};

	for (uint32_t i = 1; i < length; i++){
		if (arr[i] < min.value){
			min.idx = i;
			min.value = arr[i];
		}
	}
	return min;
}

static void update_encoders(void){
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];
		// all encoder timers wrap at 65535 (TIM2 too), so 16-bit maths handles wraparound
		uint16_t now = (uint16_t)__HAL_TIM_GET_COUNTER(m->enc_timer);
		int16_t delta = (int16_t)(now - m->enc_last);
		m->enc_last = now;

		if (m->enc_invert){
			delta = (int16_t)(-delta);
		}

		m->position_ticks += delta;
		m->speed_ticks    += delta;
	}
}

static int32_t clamp_i32(int32_t x, int32_t lo, int32_t hi){
	if (x < lo) return lo;
	if (x > hi) return hi;
	return x;
}

// Position sync: each leg is compared with the AVERAGE position of all legs.
// A leg ahead of the average is slowed, a leg behind is sped up (one PID + anti-windup per leg).
static void sync_actuators(void){
#if !SYNC_ENABLE
	return;   // open-loop test: legs stay at BASE_DUTY
#endif
	if (motor_state != FORWARD && motor_state != BACKWARD) return;

	int32_t sum = 0;
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		sum += h_bridge[i].position_ticks;
	}
	int32_t mean = sum / (int32_t)ACTUATOR_COUNT;

	// Safety: any leg too far from the average -> stop all
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		int32_t dev = h_bridge[i].position_ticks - mean;
		if (dev > ERR_LIMIT || dev < -ERR_LIMIT){
			motors_sleep();
			motor_state = SLEEP_STANDBY;
			fault = 1U;
			return;
		}
	}

	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		int32_t raw = h_bridge[i].position_ticks - mean;       // >0 = ahead of average (extending)
		int32_t err = (motor_state == BACKWARD) ? -raw : raw;  // retracting: "ahead" = smaller position

		// P and D
		float p_term = KP * (float)err;
		float d_term = KD * (float)(err - err_prev[i]);
		err_prev[i] = err;

		// Tentative integral (hard cap kept as a backstop)
		float i_new = i_acc[i] + KI * (float)err;
		if (i_new >  i_limit) i_new =  i_limit;
		if (i_new < -i_limit) i_new = -i_limit;

		// Would this output saturate this leg?
		int32_t u_try = (int32_t)(p_term + i_new + d_term);
		int32_t d_try = duty_base - u_try;
		uint8_t sat_low  = (d_try < duty_min);   // leader already pushed to the floor
		uint8_t sat_high = (d_try > duty_max);   // laggard already pushed to the ceiling

		// Anti-windup (conditional integration)
		if (!((sat_low && err > 0) || (sat_high && err < 0))){
			i_acc[i] = i_new;
		}

		int32_t u    = (int32_t)(p_term + i_acc[i] + d_term);
		int32_t duty = clamp_i32(duty_base - u, duty_min, duty_max);

		sync_error[i] = err;
		duty_cmd[i]   = duty;
		__HAL_TIM_SET_COMPARE(h_bridge[i].timer, h_bridge[i].channel, (uint32_t)duty);
	}
}

// ---- UART: non-blocking transmit through a ring buffer (no printf, never waits) ----
static uint16_t tx_free(void){
	return (uint16_t)((tx_tail - tx_head - 1U) & (TX_BUF_SIZE - 1U));
}

static void uart_write(const char *s, uint16_t n){
	for (uint16_t i = 0; i < n; i++){
		tx_buf[tx_head] = (uint8_t)s[i];
		tx_head = (uint16_t)((tx_head + 1U) & (TX_BUF_SIZE - 1U));
	}
}

// call every main-loop pass: moves bytes into the UART while it has room
static void uart_pump(void){
	while (tx_tail != tx_head && __HAL_UART_GET_FLAG(&huart2, UART_FLAG_TXE)){
		huart2.Instance->TDR = tx_buf[tx_tail];
		tx_tail = (uint16_t)((tx_tail + 1U) & (TX_BUF_SIZE - 1U));
	}
}

// append printf-style text to b at *len (stops quietly if the buffer is full)
static void buf_add(char *b, size_t size, size_t *len, const char *fmt, ...){
	if (*len >= size) return;
	va_list ap;
	va_start(ap, fmt);
	int n = vsnprintf(b + *len, size - *len, fmt, ap);
	va_end(ap);
	if (n > 0) *len += (size_t)n;
}

// Rewrites the same 6 status lines (cursor sits at the end of the last line).
// Prints one column per leg, so it works for any ACTUATOR_COUNT.
static void print_status(const int32_t s[], minResult mn){
	static char b[640];   // static: the default stack is only 1 KB
	const size_t sz = sizeof(b);
	size_t len = 0;

	buf_add(b, sz, &len, "\033[5A\r\033[2Kspeed:");
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++) buf_add(b, sz, &len, " %6ld", (long)s[i]);

	static const char *const state_name[] = {"SLEEP", "FORWARD", "BRAKE", "BACKWARD", "HOMING"};
	buf_add(b, sz, &len, "\r\n\r\033[2Kstate=%s  min speed=%6lu  motor index=%lu",
	        state_name[motor_state], (unsigned long)mn.value, (unsigned long)mn.idx);

	buf_add(b, sz, &len, "\r\n\r\033[2Kpos:  ");
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++) buf_add(b, sz, &len, " %8ld", (long)h_bridge[i].position_ticks);

	buf_add(b, sz, &len, "\r\n\r\033[2Kerr:  ");
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++) buf_add(b, sz, &len, " %6ld", (long)sync_error[i]);

	buf_add(b, sz, &len, "\r\n\r\033[2Kduty: ");
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++) buf_add(b, sz, &len, " %5ld", (long)duty_cmd[i]);
	buf_add(b, sz, &len, "  %s",
	        (motor_state == HOMING) ? "HOMING (press when all retracted)" :
	        fault ? "FAULT: press to home" : "");

#if CAN_ENABLE
	buf_add(b, sz, &len, "\r\n\r\033[2KCAN tx=%lu rx=%lu last=0x%03lX [",
	        (unsigned long)can_tx_count, (unsigned long)can_rx_count, (unsigned long)can_last_rx_id);
	for (uint8_t i = 0; i < 8U; i++) buf_add(b, sz, &len, i ? " %02X" : "%02X", can_last_rx_data[i]);
	buf_add(b, sz, &len, "]");
#else
	buf_add(b, sz, &len, "\r\n\r\033[2KCAN off");
#endif

	// drop this frame rather than ever blocking the control loop
	if (len > 0 && len < sz && tx_free() >= (uint16_t)len){
		uart_write(b, (uint16_t)len);
	}
}

// ---- CAN (FDCAN1 in classic mode) ----
static void can_init(void){
	// Filter 0: accept every standard ID into RX FIFO0 (mask 0 = match everything).
	// Needs Std Filters Nbr = 1 in CubeMX.
	FDCAN_FilterTypeDef f = {0};
	f.IdType       = FDCAN_STANDARD_ID;
	f.FilterIndex  = 0;
	f.FilterType   = FDCAN_FILTER_MASK;
	f.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
	f.FilterID1    = 0x000;   // ID
	f.FilterID2    = 0x000;   // mask
	if (HAL_FDCAN_ConfigFilter(&hfdcan1, &f) != HAL_OK) Error_Handler();

	// reject anything that doesn't match a filter
	if (HAL_FDCAN_ConfigGlobalFilter(&hfdcan1, FDCAN_REJECT, FDCAN_REJECT,
	                                 FDCAN_FILTER_REMOTE, FDCAN_FILTER_REMOTE) != HAL_OK) Error_Handler();

	if (HAL_FDCAN_Start(&hfdcan1) != HAL_OK) Error_Handler();
}

// queue one 8-byte frame; skipped (not waited for) if the TX FIFO is full
static void can_send(uint32_t id, const uint8_t data[8]){
	if (HAL_FDCAN_GetTxFifoFreeLevel(&hfdcan1) == 0U) return;

	FDCAN_TxHeaderTypeDef h = {0};
	h.Identifier          = id;
	h.IdType              = FDCAN_STANDARD_ID;
	h.TxFrameType         = FDCAN_DATA_FRAME;
	h.DataLength          = FDCAN_DLC_BYTES_8;
	h.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
	h.BitRateSwitch       = FDCAN_BRS_OFF;
	h.FDFormat            = FDCAN_CLASSIC_CAN;
	h.TxEventFifoControl  = FDCAN_NO_TX_EVENTS;
	h.MessageMarker       = 0;

	if (HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1, &h, (uint8_t *)data) == HAL_OK){
		can_tx_count++;
	}
}

static void can_send_status(void){
	uint8_t d[8] = {0};

	d[0] = (uint8_t)motor_state;
	d[1] = fault;
	d[2] = can_counter++;
	can_send(CAN_ID_STATUS, d);

	// positions, two legs per frame; a leg that isn't fitted is sent as 0
	int32_t pos[4] = {0, 0, 0, 0};
	for (uint8_t i = 0; i < ACTUATOR_COUNT && i < 4U; i++){
		pos[i] = h_bridge[i].position_ticks;
	}

	memcpy(&d[0], &pos[0], 4);
	memcpy(&d[4], &pos[1], 4);
	can_send(CAN_ID_POS_12, d);

	memcpy(&d[0], &pos[2], 4);
	memcpy(&d[4], &pos[3], 4);
	can_send(CAN_ID_POS_34, d);
}

// read every waiting frame (polled, so no FDCAN interrupt is needed)
static void can_poll_rx(void){
	while (HAL_FDCAN_GetRxFifoFillLevel(&hfdcan1, FDCAN_RX_FIFO0) > 0U){
		FDCAN_RxHeaderTypeDef rh;
		uint8_t rd[64];   // sized for the largest frame the HAL can copy
		if (HAL_FDCAN_GetRxMessage(&hfdcan1, FDCAN_RX_FIFO0, &rh, rd) != HAL_OK) break;
		can_last_rx_id = rh.Identifier;
		memcpy(can_last_rx_data, rd, sizeof(can_last_rx_data));
		can_rx_count++;
		// TODO: decode commands here once the CAN message format is decided
	}
}

// Button: step through motor states
static void handle_button(void){
	if (fault && motor_state == SLEEP_STANDBY){
		// after a fault: retract all open-loop until they sit on their end stops
		motor_state = HOMING;
		move_all_generic(REVERSE);
	}
	else if (motor_state == HOMING){
		// all fully retracted: stop and call this position zero
		motors_sleep();
		for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
			h_bridge[i].position_ticks = 0;
		}
		fault = 0U;
		motor_state = SLEEP_STANDBY;
	}
	else switch (motor_state){
		case SLEEP_STANDBY:
			motor_state = FORWARD;
			move_all_generic(GO);
			break;

		case FORWARD:
			motor_state = BRAKE;
			motors_brake();
			break;

		case BRAKE:
			motor_state = BACKWARD;
			move_all_generic(REVERSE);
			break;

		case BACKWARD:
		default:
			motor_state = SLEEP_STANDBY;
			motors_sleep();
			break;
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

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_FDCAN1_Init();
  MX_TIM1_Init();
  MX_TIM3_Init();
  MX_TIM4_Init();
  MX_TIM8_Init();
  MX_USART2_UART_Init();
  MX_TIM2_Init();
  /* USER CODE BEGIN 2 */
  duty_limits_init();

  // start only the encoders of the legs in use
  for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
      if (HAL_TIM_Encoder_Start(h_bridge[i].enc_timer, TIM_CHANNEL_ALL) != HAL_OK) Error_Handler();
      h_bridge[i].enc_last = (uint16_t)__HAL_TIM_GET_COUNTER(h_bridge[i].enc_timer);
  }

#if CAN_ENABLE
  can_init();
#endif
  /* USER CODE END 2 */

  /* Initialize leds */
  BSP_LED_Init(LED_GREEN);

  /* Initialize USER push-button, will be used to trigger an interrupt each time it's pressed.*/
  BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  minResult current_minSpeed = {0};
  uint32_t last_enc_ms = 0;
  uint32_t last_button_ms = 0U - BUTTON_DEBOUNCE_MS;

  // Banner + 5 blank lines. The status block then rewrites 6 lines upward from the cursor.
  static const char banner[] = "\r\nSTM32G431 leg sync started/reset\r\n\r\n\r\n\r\n\r\n\r\n";
  uart_write(banner, (uint16_t)(sizeof(banner) - 1U));

#if AUTO_START
  // extend all legs straight away; the button still works (brake -> retract -> stop)
  motor_state = FORWARD;
  move_all_generic(GO);
#endif

  HAL_GPIO_WritePin(M1_A_GPIO_Port, M1_A_Pin, 1);
  HAL_GPIO_WritePin(M1_B_GPIO_Port, M1_B_Pin, 0);
  HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
  while (1)
  {
	  uint32_t now = HAL_GetTick();

	  // drain the UART buffer (never waits)
	  uart_pump();

#if CAN_ENABLE
	  // read any CAN frames that arrived
	  can_poll_rx();
#endif

	  //------------------- Read encoders + sync every 10 ms ----------------------
	  if ((uint32_t)(now - last_enc_ms) >= CTRL_PERIOD_MS)
	  {
		  last_enc_ms = now;
		  update_encoders();
		  sync_actuators();
	  }

#if CAN_ENABLE
	  //------------------- CAN status every 100 ms ----------------------
	  if ((uint32_t)(now - last_can_ms) >= CAN_PERIOD_MS)
	  {
		  last_can_ms = now;
		  can_send_status();
	  }
#endif

	  //------------------- Print every 100 ms (updates the same 6 lines) ----------------------
	  if ((uint32_t)(now - last_uart_print_ms) >= PRINT_PERIOD_MS)
	  {
		  last_uart_print_ms = now;

		  // grab speed (ticks per 100 ms, signed) and reset for the next window
		  int32_t s[ACTUATOR_COUNT];
		  for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
			  s[i] = h_bridge[i].speed_ticks;
			  h_bridge[i].speed_ticks = 0;
			  speeds[i] = (uint32_t)((s[i] < 0) ? -s[i] : s[i]);
		  }
		  // findmin compares magnitudes, so it works extending or retracting
		  current_minSpeed = simple_findmin(speeds, ACTUATOR_COUNT);
		  print_status(s, current_minSpeed);

		  // green LED: flashing = FORWARD, solid = BACKWARD/HOMING, off = SLEEP/BRAKE
		  if (motor_state == FORWARD)                                BSP_LED_Toggle(LED_GREEN);
		  else if (motor_state == BACKWARD || motor_state == HOMING) BSP_LED_On(LED_GREEN);
		  else                                                       BSP_LED_Off(LED_GREEN);
	  }

	  //------------------- Button: step through motor states (debounced) ----------------------
	  if (button_event)
	  {
		  button_event = 0U;
		  if ((uint32_t)(now - last_button_ms) >= BUTTON_DEBOUNCE_MS)
		  {
			  last_button_ms = now;
			  handle_button();
		  }
	  }

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
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

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV4;
  RCC_OscInitStruct.PLL.PLLN = 85;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief FDCAN1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_FDCAN1_Init(void)
{

  /* USER CODE BEGIN FDCAN1_Init 0 */

  /* USER CODE END FDCAN1_Init 0 */

  /* USER CODE BEGIN FDCAN1_Init 1 */

  /* USER CODE END FDCAN1_Init 1 */
  hfdcan1.Instance = FDCAN1;
  hfdcan1.Init.ClockDivider = FDCAN_CLOCK_DIV1;
  hfdcan1.Init.FrameFormat = FDCAN_FRAME_CLASSIC;
  hfdcan1.Init.Mode = FDCAN_MODE_NORMAL;
  hfdcan1.Init.AutoRetransmission = DISABLE;
  hfdcan1.Init.TransmitPause = DISABLE;
  hfdcan1.Init.ProtocolException = DISABLE;
  hfdcan1.Init.NominalPrescaler = 68;
  hfdcan1.Init.NominalSyncJumpWidth = 4;
  hfdcan1.Init.NominalTimeSeg1 = 15;
  hfdcan1.Init.NominalTimeSeg2 = 4;
  hfdcan1.Init.DataPrescaler = 1;
  hfdcan1.Init.DataSyncJumpWidth = 1;
  hfdcan1.Init.DataTimeSeg1 = 1;
  hfdcan1.Init.DataTimeSeg2 = 1;
  hfdcan1.Init.StdFiltersNbr = 0;
  hfdcan1.Init.ExtFiltersNbr = 0;
  hfdcan1.Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
  if (HAL_FDCAN_Init(&hfdcan1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN FDCAN1_Init 2 */

  /* USER CODE END FDCAN1_Init 2 */

}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 0;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 65535;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 6;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 6;
  if (HAL_TIM_Encoder_Init(&htim1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_UPDATE;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_ENABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 65535;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 6;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 6;
  if (HAL_TIM_Encoder_Init(&htim2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 3399;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 3000;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.Pulse = 0;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */
  HAL_TIM_MspPostInit(&htim3);

}

/**
  * @brief TIM4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM4_Init(void)
{

  /* USER CODE BEGIN TIM4_Init 0 */

  /* USER CODE END TIM4_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM4_Init 1 */

  /* USER CODE END TIM4_Init 1 */
  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 0;
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 65535;
  htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 6;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 6;
  if (HAL_TIM_Encoder_Init(&htim4, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM4_Init 2 */

  /* USER CODE END TIM4_Init 2 */

}

/**
  * @brief TIM8 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM8_Init(void)
{

  /* USER CODE BEGIN TIM8_Init 0 */

  /* USER CODE END TIM8_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM8_Init 1 */

  /* USER CODE END TIM8_Init 1 */
  htim8.Instance = TIM8;
  htim8.Init.Prescaler = 0;
  htim8.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim8.Init.Period = 65535;
  htim8.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim8.Init.RepetitionCounter = 0;
  htim8.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 6;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 6;
  if (HAL_TIM_Encoder_Init(&htim8, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim8, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM8_Init 2 */

  /* USER CODE END TIM8_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  huart2.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart2.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart2.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart2, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart2, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

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
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOC, M4_A_Pin|M4_B_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, M1_A_Pin|M1_B_Pin|M2_B_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, M2_A_Pin|M3_B_Pin|M3_A_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : M4_A_Pin M4_B_Pin */
  GPIO_InitStruct.Pin = M4_A_Pin|M4_B_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : M1_A_Pin M1_B_Pin M2_B_Pin */
  GPIO_InitStruct.Pin = M1_A_Pin|M1_B_Pin|M2_B_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : M2_A_Pin M3_B_Pin M3_A_Pin */
  GPIO_InitStruct.Pin = M2_A_Pin|M3_B_Pin|M3_A_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void BSP_PB_Callback(Button_TypeDef Button)
{
    if (Button == BUTTON_USER)
    {
        button_event = 1U;
    }
}
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

#ifdef  USE_FULL_ASSERT
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
