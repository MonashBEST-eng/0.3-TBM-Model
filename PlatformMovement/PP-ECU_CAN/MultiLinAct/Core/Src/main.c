/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Stewart Platform ECU - Controls 2 linear actuators via GPIO
  *                   Communicates over CAN (ID 0x100 commands, 0x101 status)
  ******************************************************************************
*/
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdbool.h>
#include "usbd_cdc_if.h"
#include <stdarg.h>
#include <string.h>

static void debug_printf(const char *fmt, ...)
{
    char buf[256];

    va_list args;
    va_start(args, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    if (len <= 0) return;
    if (len > sizeof(buf)) len = sizeof(buf);

    CDC_Transmit_FS((uint8_t*)buf, len);
}

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

typedef struct {
    int8_t   dir;          // -1 = retract, +1 = extend, 0 = no move
    uint32_t duration_ms;
} MoveCmd_t;

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
FDCAN_HandleTypeDef hfdcan1;

TIM_HandleTypeDef htim2;

/* USER CODE BEGIN PV */

MoveCmd_t cmd[2] = {{0,0}, {0,0}};
volatile bool prepared = false;
volatile bool motion_active = false;
uint32_t motion_start_tick = 0;

// CAN TX helper
FDCAN_TxHeaderTypeDef TxHeader;
uint8_t txData[8];

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_FDCAN1_Init(void);
static void MX_TIM2_Init(void);
/* USER CODE BEGIN PFP */

typedef enum {
    MOTOR_STATE_COAST,
    MOTOR_STATE_FORWARD,
    MOTOR_STATE_REVERSE,
    MOTOR_STATE_BRAKE
} Motor_State_t;

void Motor1_Control(Motor_State_t state);
void Motor2_Control(Motor_State_t state);
void Motor1_Sleep(uint8_t sleep);
void Motor2_Sleep(uint8_t sleep);
void SendStatus(uint8_t code);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

//void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *hfdcan, uint32_t RxFifo0ITs)
//{
//
//
//	debug_printf("[IRQ] RX interrupt fired\r\n");
//
//    if ((RxFifo0ITs & FDCAN_IT_RX_FIFO0_NEW_MESSAGE) == 0)
//        return;
//
//    FDCAN_RxHeaderTypeDef RxHeader;
//    uint8_t rxData[8];
//
//    if (HAL_FDCAN_GetRxMessage(hfdcan, FDCAN_RX_FIFO0, &RxHeader, rxData) != HAL_OK)
//        return;
//
//
//    debug_printf("[IRQ] RX ID=0x%03lX DLC=%lu\r\n",
//                 RxHeader.Identifier,
//                 RxHeader.DataLength >> 16);
//
//
//    // Only handle our command ID 0x100
//    if (RxHeader.Identifier != 0x100 || RxHeader.RxFrameType != FDCAN_DATA_FRAME)
//        return;
//
//    // PREPARE: DLC == 6 -> [d1, d2, t1_lo, t1_hi, t2_lo, t2_hi]
//    if (RxHeader.DataLength == FDCAN_DLC_BYTES_6)
//    {
//        int8_t d1 = (int8_t)rxData[0];
//        int8_t d2 = (int8_t)rxData[1];
//
//        uint16_t t1 = (uint16_t)rxData[2] | ((uint16_t)rxData[3] << 8);
//        uint16_t t2 = (uint16_t)rxData[4] | ((uint16_t)rxData[5] << 8);
//
//        cmd[0].dir         = d1;
//        cmd[0].duration_ms = t1;
//        cmd[1].dir         = d2;
//        cmd[1].duration_ms = t2;
//
//        prepared      = true;
//        motion_active = false;
//
//        debug_printf("[PREPARE] d1=%d d2=%d t1=%u t2=%u\r\n",
//                     d1, d2, t1, t2);
//
//        // Tell PC we're ready
//        SendStatus(0x01); // PREPARED
//    }
//    // START: DLC == 1, data[0] == 0xFF
//    else if (RxHeader.DataLength == FDCAN_DLC_BYTES_1 && rxData[0] == 0xFF)
//    {
//    	debug_printf("[START] received, prepared=%d\r\n", prepared);
//
//        if (prepared)
//        {
//            Motor1_Sleep(0);
//            Motor2_Sleep(0);
//
//            // Motor 1 direction
//            if (cmd[0].dir > 0)
//                Motor1_Control(MOTOR_STATE_FORWARD);
//            else if (cmd[0].dir < 0)
//                Motor1_Control(MOTOR_STATE_REVERSE);
//            else
//                Motor1_Control(MOTOR_STATE_COAST);
//
//            // Motor 2 direction
//            if (cmd[1].dir > 0)
//                Motor2_Control(MOTOR_STATE_FORWARD);
//            else if (cmd[1].dir < 0)
//                Motor2_Control(MOTOR_STATE_REVERSE);
//            else
//                Motor2_Control(MOTOR_STATE_COAST);
//
//            if (cmd[0].duration_ms == 0 && cmd[1].duration_ms == 0)
//            {
//                // Nothing to move
//                Motor1_Sleep(1);
//                Motor2_Sleep(1);
//                prepared      = false;
//                motion_active = false;
//
//                SendStatus(0x03); // DONE
//            }
//            else
//            {
//                motion_start_tick = HAL_GetTick();
//                motion_active     = true;
//
//                SendStatus(0x02); // MOVING
//            }
//        }
//    }
//}

//void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *hfdcan, uint32_t RxFifo0ITs)
//{
//    (void)RxFifo0ITs;  // we ignore the flags for now
//    debug_printf("[IRQ] RX interrupt fired\r\n");
//
//    FDCAN_RxHeaderTypeDef RxHeader;
//    uint8_t rxData[8];
//
//    // Always try to fetch one frame from FIFO0
//    if (HAL_FDCAN_GetRxMessage(hfdcan, FDCAN_RX_FIFO0, &RxHeader, rxData) != HAL_OK)
//    {
//        debug_printf("[IRQ] HAL_FDCAN_GetRxMessage FAILED\r\n");
//        return;
//    }
//
//    // Convert HAL DLC encoding to actual byte count (0..8)
//    uint32_t dlc_bytes = RxHeader.DataLength >> 16;
//
//    debug_printf("[IRQ] RX ID=0x%03lX DLC=%lu, IdType=%lu, FrameType=%lu\r\n",
//                 RxHeader.Identifier,
//                 dlc_bytes,
//                 (unsigned long)RxHeader.IdType,
//                 (unsigned long)RxHeader.RxFrameType);
//
//    debug_printf("[IRQ] Data:");
//    for (uint32_t i = 0; i < dlc_bytes; i++)
//    {
//        char tmp[8];
//        snprintf(tmp, sizeof(tmp), " %02X", rxData[i]);
//        debug_printf("%s", tmp);
//    }
//    debug_printf("\r\n");
//
//    // Only handle our command ID 0x100 as a data frame
//    if (RxHeader.Identifier != 0x100 || RxHeader.RxFrameType != FDCAN_DATA_FRAME)
//    {
//        debug_printf("[IRQ] Ignored frame (ID=0x%03lX, type=%lu)\r\n",
//                     RxHeader.Identifier,
//                     (unsigned long)RxHeader.RxFrameType);
//        return;
//    }
//
//    // ===================== PREPARE =====================
//    // Expect exactly 6 bytes: [d1, d2, t1_lo, t1_hi, t2_lo, t2_hi]
//    if (dlc_bytes == 6)
//    {
//        int8_t   d1 = (int8_t)rxData[0];
//        int8_t   d2 = (int8_t)rxData[1];
//        uint16_t t1 = (uint16_t)rxData[2] | ((uint16_t)rxData[3] << 8);
//        uint16_t t2 = (uint16_t)rxData[4] | ((uint16_t)rxData[5] << 8);
//
//        cmd[0].dir         = d1;
//        cmd[0].duration_ms = t1;
//        cmd[1].dir         = d2;
//        cmd[1].duration_ms = t2;
//
//        prepared      = true;
//        motion_active = false;
//
//        debug_printf("[PREPARE] d1=%d d2=%d t1=%u t2=%u\r\n", d1, d2, t1, t2);
//
//        // Tell PC we're ready
//        SendStatus(0x01); // PREPARED
//        return;
//    }
//
//    // ====================== START ======================
//    // Any 1+ byte frame with first byte 0xFF is treated as START
//    if (dlc_bytes >= 1 && rxData[0] == 0xFF)
//    {
//        debug_printf("[START] received, prepared=%d\r\n", prepared ? 1 : 0);
//
//        if (prepared)
//        {
//            Motor1_Sleep(0);
//            Motor2_Sleep(0);
//
//            // Motor 1 direction
//            if (cmd[0].dir > 0)
//                Motor1_Control(MOTOR_STATE_FORWARD);
//            else if (cmd[0].dir < 0)
//                Motor1_Control(MOTOR_STATE_REVERSE);
//            else
//                Motor1_Control(MOTOR_STATE_COAST);
//
//            // Motor 2 direction
//            if (cmd[1].dir > 0)
//                Motor2_Control(MOTOR_STATE_FORWARD);
//            else if (cmd[1].dir < 0)
//                Motor2_Control(MOTOR_STATE_REVERSE);
//            else
//                Motor2_Control(MOTOR_STATE_COAST);
//
//            if (cmd[0].duration_ms == 0 && cmd[1].duration_ms == 0)
//            {
//                debug_printf("[START] Zero durations, immediately DONE\r\n");
//
//                Motor1_Sleep(1);
//                Motor2_Sleep(1);
//                prepared      = false;
//                motion_active = false;
//
//                SendStatus(0x03); // DONE
//            }
//            else
//            {
//                motion_start_tick = HAL_GetTick();
//                motion_active     = true;
//
//                debug_printf("[START] Motion active: t1=%u t2=%u\r\n",
//                             cmd[0].duration_ms, cmd[1].duration_ms);
//
//                SendStatus(0x02); // MOVING
//            }
//        }
//        else
//        {
//            debug_printf("[START] Ignored because not prepared\r\n");
//        }
//
//        return;
//    }
//
//    // ================== UNKNOWN CMD ====================
//    debug_printf("[IRQ] Unknown command frame (DLC=%lu, first=0x%02X)\r\n",
//                 dlc_bytes, (dlc_bytes > 0) ? rxData[0] : 0x00);
//}


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
  MX_TIM2_Init();
  MX_USB_Device_Init();
  /* USER CODE BEGIN 2 */

  // Start with drivers asleep and coasting
  Motor1_Sleep(1);
  Motor2_Sleep(1);

  // Start FDCAN and enable RX FIFO0 new message interrupt
  if (HAL_FDCAN_Start(&hfdcan1) != HAL_OK)
  {
      Error_Handler();
  }

  debug_printf("FDCAN1 started\r\n");


  if (HAL_FDCAN_ActivateNotification(&hfdcan1,
                                     FDCAN_IT_RX_FIFO0_NEW_MESSAGE,
                                     0) != HAL_OK)
  {
      Error_Handler();
  }

  debug_printf("FDCAN1 RX FIFO0 interrupt enabled\r\n");


  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
	// ======= NEW: Poll CAN RX FIFO0 for commands =======
	uint32_t fillLevel = HAL_FDCAN_GetRxFifoFillLevel(&hfdcan1, FDCAN_RX_FIFO0);
	if (fillLevel > 0)
	{
	  FDCAN_RxHeaderTypeDef RxHeader;
	  uint8_t rxData[8];

	  if (HAL_FDCAN_GetRxMessage(&hfdcan1, FDCAN_RX_FIFO0, &RxHeader, rxData) == HAL_OK)
	  {
		  // 🔹 NEW: compute DLC once, and log what we actually received
		  uint32_t dlc_bytes = RxHeader.DataLength >> 16;

		  debug_printf("[CAN] RX ID=0x%03lX, IdType=%lu, FrameType=%lu, DLC=%lu\r\n",
					   RxHeader.Identifier,
					   (unsigned long)RxHeader.IdType,
					   (unsigned long)RxHeader.RxFrameType,
					   dlc_bytes);

		  debug_printf("[CAN] Data bytes:");
		  for (uint32_t i = 0; i < 8; i++)    // log all 8 slots
		  {
			  char tmp[8];
			  snprintf(tmp, sizeof(tmp), " %02X", rxData[i]);
			  debug_printf("%s", tmp);
		  }
		  debug_printf("\r\n");

		  // Only handle standard data frames on ID 0x100
		  if (RxHeader.IdType == FDCAN_STANDARD_ID &&
		      RxHeader.RxFrameType == FDCAN_DATA_FRAME &&
		      RxHeader.Identifier == 0x100)
		  {
		      uint32_t dlc_bytes = RxHeader.DataLength >> 16;

		      // 🔍 We log DLC, but we don't trust it for logic anymore
		      debug_printf("[CAN] RX ID=0x%03lX, IdType=%lu, FrameType=%lu, DLC=%lu\r\n",
		                   RxHeader.Identifier,
		                   (unsigned long)RxHeader.IdType,
		                   (unsigned long)RxHeader.RxFrameType,
		                   dlc_bytes);

		      debug_printf("[CAN] Data bytes:");
		      for (uint32_t i = 0; i < 8; i++)
		      {
		          char tmp[8];
		          snprintf(tmp, sizeof(tmp), " %02X", rxData[i]);
		          debug_printf("%s", tmp);
		      }
		      debug_printf("\r\n");

		      // ======= START: first byte 0xFF =======
		      if (rxData[0] == 0xFF)
		      {
		          debug_printf("[START] received, prepared=%d\r\n",
		                       prepared ? 1 : 0);

		          if (prepared)
		          {
		              Motor1_Sleep(0);
		              Motor2_Sleep(0);

		              // Motor 1 direction
		              if (cmd[0].dir > 0)
		                  Motor1_Control(MOTOR_STATE_FORWARD);
		              else if (cmd[0].dir < 0)
		                  Motor1_Control(MOTOR_STATE_REVERSE);
		              else
		                  Motor1_Control(MOTOR_STATE_COAST);

		              // Motor 2 direction
		              if (cmd[1].dir > 0)
		                  Motor2_Control(MOTOR_STATE_FORWARD);
		              else if (cmd[1].dir < 0)
		                  Motor2_Control(MOTOR_STATE_REVERSE);
		              else
		                  Motor2_Control(MOTOR_STATE_COAST);

		              if (cmd[0].duration_ms == 0 && cmd[1].duration_ms == 0)
		              {
		                  debug_printf("[START] Zero durations, immediately DONE\r\n");

		                  Motor1_Sleep(1);
		                  Motor2_Sleep(1);
		                  prepared      = false;
		                  motion_active = false;

		                  SendStatus(0x03); // DONE
		              }
		              else
		              {
		                  motion_start_tick = HAL_GetTick();
		                  motion_active     = true;

		                  debug_printf("[START] Motion active: t1=%u t2=%u\r\n",
		                               cmd[0].duration_ms, cmd[1].duration_ms);

		                  SendStatus(0x02); // MOVING
		              }
		          }
		          else
		          {
		              debug_printf("[START] Ignored because not prepared\r\n");
		          }
		      }
		      // ======= PREPARE: assume 6-byte payload =======
		      else
		      {
		          int8_t   d1 = (int8_t)rxData[0];
		          int8_t   d2 = (int8_t)rxData[1];
		          uint16_t t1 = (uint16_t)rxData[2] | ((uint16_t)rxData[3] << 8);
		          uint16_t t2 = (uint16_t)rxData[4] | ((uint16_t)rxData[5] << 8);

		          cmd[0].dir         = d1;
		          cmd[0].duration_ms = t1;
		          cmd[1].dir         = d2;
		          cmd[1].duration_ms = t2;

		          prepared      = true;
		          motion_active = false;

		          debug_printf("[PREPARE] d1=%d d2=%d t1=%u t2=%u\r\n",
		                       d1, d2, t1, t2);

		          SendStatus(0x01);   // PREPARED
		      }
		  }
	  }
	}

	if (motion_active)
	{
		uint32_t elapsed = HAL_GetTick() - motion_start_tick;

		if (cmd[0].duration_ms > 0 && elapsed >= cmd[0].duration_ms)
			Motor1_Control(MOTOR_STATE_COAST);

		if (cmd[1].duration_ms > 0 && elapsed >= cmd[1].duration_ms)
			Motor2_Control(MOTOR_STATE_COAST);

		bool all_done = (cmd[0].duration_ms == 0 || elapsed >= cmd[0].duration_ms) &&
						(cmd[1].duration_ms == 0 || elapsed >= cmd[1].duration_ms);

		if (all_done || elapsed > 10000)  // 10s safety timeout
		{
			motion_active = false;
			prepared      = false;

			SendStatus(0x03); // DONE

			Motor1_Sleep(1);
			Motor2_Sleep(1);
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
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48|RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV1;
  RCC_OscInitStruct.PLL.PLLN = 42;
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
  hfdcan1.Init.AutoRetransmission = ENABLE;
  hfdcan1.Init.TransmitPause = DISABLE;
  hfdcan1.Init.ProtocolException = DISABLE;
  hfdcan1.Init.NominalPrescaler = 84;
  hfdcan1.Init.NominalSyncJumpWidth = 1;
  hfdcan1.Init.NominalTimeSeg1 = 15;
  hfdcan1.Init.NominalTimeSeg2 = 4;
  hfdcan1.Init.DataPrescaler = 1;
  hfdcan1.Init.DataSyncJumpWidth = 1;
  hfdcan1.Init.DataTimeSeg1 = 1;
  hfdcan1.Init.DataTimeSeg2 = 1;
  hfdcan1.Init.StdFiltersNbr = 1;
  hfdcan1.Init.ExtFiltersNbr = 0;
  hfdcan1.Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
  if (HAL_FDCAN_Init(&hfdcan1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN FDCAN1_Init 2 */
  // Configure a standard ID filter to accept ID 0x100 into RX FIFO 0
  FDCAN_FilterTypeDef sFilterConfig = {0};
  sFilterConfig.IdType       = FDCAN_STANDARD_ID;
  sFilterConfig.FilterIndex  = 0;
  sFilterConfig.FilterType   = FDCAN_FILTER_MASK;
  sFilterConfig.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
  sFilterConfig.FilterID1    = 0x000;  // ID to match
  sFilterConfig.FilterID2    = 0x000;  // mask: accept only 0x100

  if (HAL_FDCAN_ConfigFilter(&hfdcan1, &sFilterConfig) != HAL_OK)
  {
      Error_Handler();
  }

  debug_printf("Filter installed: ID=0x100 -> FIFO0\r\n");

  // Enable FDCAN1 interrupt line 0 in NVIC
  HAL_NVIC_SetPriority(FDCAN1_IT0_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(FDCAN1_IT0_IRQn);

  /* USER CODE END FDCAN1_Init 2 */

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

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 8499;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
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
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, H1_FWD_Pin|H1_REV_Pin|H2_FWD_Pin|H2_REV_Pin
                          |H1_SLEEP_Pin|H2_SLEEP_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : H1_FWD_Pin H1_REV_Pin H2_FWD_Pin H2_REV_Pin
                           H1_SLEEP_Pin H2_SLEEP_Pin */
  GPIO_InitStruct.Pin = H1_FWD_Pin|H1_REV_Pin|H2_FWD_Pin|H2_REV_Pin
                          |H1_SLEEP_Pin|H2_SLEEP_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

void Motor1_Control(Motor_State_t state)
{
    switch (state)
    {
        case MOTOR_STATE_FORWARD:
            HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_SET);
            HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_RESET);
            break;
        case MOTOR_STATE_REVERSE:
            HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_RESET);
            HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_SET);
            break;
        case MOTOR_STATE_BRAKE:
            HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_SET);
            HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_SET);
            break;
        default: // COAST
            HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_RESET);
            HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_RESET);
            break;
    }
}

void Motor2_Control(Motor_State_t state)
{
    switch (state)
    {
        case MOTOR_STATE_FORWARD:
            HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_SET);
            HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_RESET);
            break;
        case MOTOR_STATE_REVERSE:
            HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_RESET);
            HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_SET);
            break;
        case MOTOR_STATE_BRAKE:
            HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_SET);
            HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_SET);
            break;
        default: // COAST
            HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_RESET);
            HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_RESET);
            break;
    }
}

void Motor1_Sleep(uint8_t sleep)
{
    HAL_GPIO_WritePin(H1_SLEEP_GPIO_Port, H1_SLEEP_Pin,
                      sleep ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

void Motor2_Sleep(uint8_t sleep)
{
    HAL_GPIO_WritePin(H2_SLEEP_GPIO_Port, H2_SLEEP_Pin,
                      sleep ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

//void SendStatus(uint8_t code)
//{
//    TxHeader.Identifier          = 0x101;
//    TxHeader.IdType              = FDCAN_STANDARD_ID;
//    TxHeader.TxFrameType         = FDCAN_DATA_FRAME;
//    TxHeader.DataLength          = FDCAN_DLC_BYTES_1;
//    TxHeader.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
//    TxHeader.BitRateSwitch       = FDCAN_BRS_OFF;
//    TxHeader.FDFormat            = FDCAN_CLASSIC_CAN;
//    TxHeader.TxEventFifoControl  = FDCAN_NO_TX_EVENTS;
//    TxHeader.MessageMarker       = 0;
//
//    txData[0] = code;
//
//    HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1, &TxHeader, txData);
//}

void SendStatus(uint8_t code)
{
    TxHeader.Identifier          = 0x101;              // status ID
    TxHeader.IdType              = FDCAN_STANDARD_ID;
    TxHeader.TxFrameType         = FDCAN_DATA_FRAME;
    TxHeader.DataLength          = FDCAN_DLC_BYTES_1;  // 1-byte payload
    TxHeader.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    TxHeader.BitRateSwitch       = FDCAN_BRS_OFF;
    TxHeader.FDFormat            = FDCAN_CLASSIC_CAN;
    TxHeader.TxEventFifoControl  = FDCAN_NO_TX_EVENTS;
    TxHeader.MessageMarker       = 0;

    txData[0] = code;

    HAL_StatusTypeDef st =
        HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1, &TxHeader, txData);

    debug_printf("[STATUS] code=0x%02X, HAL_FDCAN_AddMessageToTxFifoQ=%d\r\n",
                 code, (int)st);
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
