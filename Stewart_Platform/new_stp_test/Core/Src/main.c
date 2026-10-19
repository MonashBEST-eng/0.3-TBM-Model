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
#include <math.h>

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

COM_InitTypeDef BspCOMInit;
FDCAN_HandleTypeDef hfdcan1;

TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

//TIMERS
typedef struct {
    uint32_t now;
    uint32_t sec_marker;
    uint32_t count;
} timer;

volatile timer timer1;
volatile timer timer2;
volatile timer timer3_CAN_UDS;
volatile uint8_t timer1_flag = 0U;

//Motor states and stuff
#define NUM_MOTORS 2
#define RUN_CALIBRATION_ON_BOOT 1U
#define CALIBRATION_TICKS       500U
#define CALIBRATION_DUTY        (full_cycle / 4U)
#define CALIBRATION_TIMEOUT_MS  15000U

typedef struct {
    volatile int32_t ticks;            // net position, signed: +forward, -backward
    volatile uint32_t distance_ticks;  // ALWAYS increments regardless of direction.
                                        // This is what a distance "quota" checks against.
    volatile uint32_t total_ticks;     // lifetime Hall edges since this boot
    uint32_t target_ticks;             // quota target for the current move, in pulses
    volatile uint8_t active;           // 1 while this motor is still moving toward target
} motor;

static motor motors[NUM_MOTORS];

// Per-motor hardware mapping: which timer/channel drives it, which GPIO pins
// set its direction, and which Hall pins belong to it.
typedef struct {
    TIM_HandleTypeDef *htim;
    uint32_t channel;
    uint16_t p_pin;          // forward-direction pin, on GPIOB
    uint16_t n_pin;          // backward-direction pin, on GPIOC
    uint16_t hall_a_pin;     // interrupt pin, on GPIOC
    GPIO_TypeDef *hall_b_port;
    uint16_t hall_b_pin;     // direction-sense pin, read (not interrupt)
} MotorHW;

static MotorHW motors_hw[NUM_MOTORS] = {
    { &htim2, TIM_CHANNEL_1, M1P_Pin, M1N_Pin, HALL_1A_Pin, GPIOB, HALL_1B_Pin },
    { &htim2, TIM_CHANNEL_2, M2P_Pin, M2N_Pin, HALL_2A_Pin, GPIOB, HALL_2B_Pin },
};

// Pulses-per-mm calibration, one per actuator. MEASURE THESE (see notes near
// moveAllMM below) - placeholder values will give wrong distances until you do.
static float pulsesPerMM[NUM_MOTORS] = {10.0f, 10.0f};

uint32_t full_cycle = 4249;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_FDCAN1_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_USART2_UART_Init(void);
/* USER CODE BEGIN PFP */
timer start_timer()
{
	timer timer;
    timer.now = HAL_GetTick();
    timer.sec_marker = 0U;
    timer.count = 0;
    return timer;
}

uint32_t elapsed(timer timer)
{
    return (uint32_t)(HAL_GetTick() - timer.now);
}

// Start motor idx moving toward target_ticks pulses of DISTANCE (not net
// position). duty is the raw CCR compare value for that motor's timer.
void motor_start(uint8_t idx, uint8_t forward, uint32_t target_ticks, uint32_t duty)
{
    MotorHW *hw = &motors_hw[idx];

    __disable_irq();
    motors[idx].distance_ticks = 0;
    __enable_irq();

    motors[idx].target_ticks = target_ticks;
    motors[idx].active = (target_ticks > 0) ? 1U : 0U;

    if (!motors[idx].active) {
        return;
    }

    if (forward) {
        HAL_GPIO_WritePin(GPIOC, hw->n_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(GPIOB, hw->p_pin, GPIO_PIN_SET);
    } else {
        HAL_GPIO_WritePin(GPIOB, hw->p_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(GPIOC, hw->n_pin, GPIO_PIN_SET);
    }

    __HAL_TIM_SET_COMPARE(hw->htim, hw->channel, duty);
    HAL_TIM_PWM_Start(hw->htim, hw->channel);
}

// Stop motor idx: cuts PWM and releases both direction pins (coast, not brake).
void motor_stop(uint8_t idx)
{
    MotorHW *hw = &motors_hw[idx];
    HAL_TIM_PWM_Stop(hw->htim, hw->channel);
    HAL_GPIO_WritePin(GPIOB, hw->p_pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOC, hw->n_pin, GPIO_PIN_RESET);
    motors[idx].active = 0U;
}

void go(void)
{
    GPIOB->BSRR = M1P_Pin | M2P_Pin;
    GPIOC->BSRR = (uint32_t)(M1N_Pin | M2N_Pin) << 16U;

    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_1, full_cycle / 2U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_2, full_cycle / 2U);

    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
}

void reverse(void)
{
    GPIOB->BSRR = (uint32_t)(M1P_Pin | M2P_Pin) << 16U;
    GPIOC->BSRR = M1N_Pin | M2N_Pin;

    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_1, full_cycle / 2U);
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_2, full_cycle / 2U);

    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
}

// Call every main-loop iteration. Independently stops each motor the instant
// IT (not the others) reaches its own distance quota.
void motors_check(void)
{
    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        if (!motors[i].active) continue;

        uint32_t d;
        __disable_irq();
        d = motors[i].distance_ticks;
        __enable_irq();

        if (d >= motors[i].target_ticks) {
            motor_stop(i);
        }
    }
}

// Command all 6 actuators at once. distancesMM[i] > 0 = extend, < 0 = retract.
// duty is the same raw CCR value applied to every motor (0..full_cycle).
//
// CALIBRATION (per actuator, update pulsesPerMM[] above):
//   1. Fully retract actuator i to a known reference point.
//   2. moveAllMM() with only actuators[i] non-zero, e.g. 100.0f, others 0.
//   3. Measure ACTUAL travel with calipers once it stops.
//   4. Read motors[i].distance_ticks (breakpoint or UART) at the moment it stopped.
//   5. pulsesPerMM[i] = distance_ticks / actual_mm_measured
//   Repeat per actuator - small mechanical variance is normal between units.
void moveAllMM(const float distancesMM[NUM_MOTORS], uint32_t duty)
{
    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        uint8_t forward = (distancesMM[i] >= 0.0f) ? 1U : 0U;
        uint32_t target = (uint32_t)(fabsf(distancesMM[i]) * pulsesPerMM[i]);
        motor_start(i, forward, target, duty);
    }

    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
}

uint8_t allMotorsDone(void)
{
    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        if (motors[i].active) return 0U;
    }
    return 1U;
}

// One-shot calibration move. Both actuators start forward with the same
// Hall-tick quota. Each actuator stops independently when it reaches the quota.
// Measure each actuator's physical travel afterwards, then calculate:
// pulsesPerMM[i] = CALIBRATION_TICKS / measured_distance_mm
static void runCalibrationSequence(void)
{
    uint32_t started_at = HAL_GetTick();
    char message[96];

    HAL_UART_Transmit(
        &huart2,
        (uint8_t *)"Calibration starting\r\n",
        sizeof("Calibration starting\r\n") - 1U,
        HAL_MAX_DELAY
    );

    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        motor_start(i, 1U, CALIBRATION_TICKS, CALIBRATION_DUTY);
    }

    // TIM1 is the internal synchronization master for TIM2 and TIM3.
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);

    while (!allMotorsDone()) {
        motors_check();

        if ((uint32_t)(HAL_GetTick() - started_at) >= CALIBRATION_TIMEOUT_MS) {
            for (uint8_t i = 0; i < NUM_MOTORS; i++) {
                if (motors[i].active) {
                    motor_stop(i);
                }
            }

            HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);
            HAL_UART_Transmit(
                &huart2,
                (uint8_t *)"Calibration timeout - both motors stopped\r\n",
                sizeof("Calibration timeout - both motors stopped\r\n") - 1U,
                HAL_MAX_DELAY
            );
            return;
        }
    }

    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);

    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        int length = snprintf(
            message,
            sizeof(message),
            "M%u: %lu calibration ticks, signed position %ld\r\n",
            (unsigned int)(i + 1U),
            (unsigned long)motors[i].distance_ticks,
            (long)motors[i].ticks
        );

        HAL_UART_Transmit(
            &huart2,
            (uint8_t *)message,
            (uint16_t)length,
            HAL_MAX_DELAY
        );
    }

    HAL_UART_Transmit(
        &huart2,
        (uint8_t *)"Calibration complete - measure each actuator travel\r\n",
        sizeof("Calibration complete - measure each actuator travel\r\n") - 1U,
        HAL_MAX_DELAY
    );
}

void testCAN()
{

}

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

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
  //uint32_t now = HAL_GetTick();
  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */


  MX_GPIO_Init();
  MX_FDCAN1_Init();
  MX_TIM1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
  HAL_UART_Transmit(
      &huart2,
      (uint8_t *)"STM32 started\r\n",
      sizeof("STM32 started\r\n") - 1,
      HAL_MAX_DELAY
  );

  /* USER CODE END 2 */

  /* Initialize leds */
  BSP_LED_Init(LED_GREEN);

  /* Initialize USER push-button, will be used to trigger an interrupt each time it's pressed.*/
  BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);

  /* Initialize COM1 port (115200, 8 bits (7-bit data + 1 stop bit), no parity */ /*
  BspCOMInit.BaudRate   = 115200;
  BspCOMInit.WordLength = COM_WORDLENGTH_8B;
  BspCOMInit.StopBits   = COM_STOPBITS_1;
  BspCOMInit.Parity     = COM_PARITY_NONE;
  BspCOMInit.HwFlowCtl  = COM_HWCONTROL_NONE;
  if (BSP_COM_Init(COM1, &BspCOMInit) != BSP_ERROR_NONE)
  {
    Error_Handler();
  }
  HAL_UART_Transmit(
      &huart2,
      (uint8_t *)"AFTER BSP\r\n",
      sizeof("AFTER BSP\r\n") - 1,
      1000
  );
*/
  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  HAL_FDCAN_Start(&hfdcan1);


  FDCAN_TxHeaderTypeDef count;

  count.Identifier = 0x123;
  count.IdType = FDCAN_STANDARD_ID;
  count.TxFrameType = FDCAN_DATA_FRAME;
  count.DataLength = FDCAN_DLC_BYTES_8;
  count.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
  count.BitRateSwitch = FDCAN_BRS_OFF;
  count.FDFormat = FDCAN_CLASSIC_CAN;
  count.TxEventFifoControl = FDCAN_NO_TX_EVENTS;
  count.MessageMarker = 0;
  uint8_t CAN_counter = 0;
  static char uart_buffer[96];
  uint32_t last_hall_log_ms;

  //if (RUN_CALIBRATION_ON_BOOT) {
  //    runCalibrationSequence();
  //}

  last_hall_log_ms = HAL_GetTick();

  // Example: extend both actuators 150mm at ~50% duty. Remove/replace this
  // with whatever triggers a move in your app (button, CAN command, etc).
  // float example_targets[NUM_MOTORS] = {150.0f, 150.0f};
  // moveAllMM(example_targets, full_cycle / 2);

  // Quick motor reset helpers (uses the PWM duty already in the CCR registers):
  // reverse();
  // go
  HAL_UART_Transmit(
      &huart2,
      (uint8_t *)"time_ms,M1_total,M2_total,M1_position,M2_position\r\n",
      sizeof("time_ms,M1_total,M2_total,M1_position,M2_position\r\n") - 1U,
      HAL_MAX_DELAY
  );
  runCalibrationSequence();
  while (1)
  {

	  // Independently stops each actuator the moment IT reaches its own quota.
	  motors_check();

	  //Task 1: LED toggle
	  	  uint32_t elapsed_time2 = elapsed(timer2);
	  	      if (elapsed_time2 - timer2.sec_marker >= 50U){
	  	    	  //BSP_LED_Toggle(LED_GREEN);
	  	    	  timer2.sec_marker += 50U;
	  	      }


	  // Log M1/M2 Hall totals and signed positions as CSV once per second.
	  uint32_t now_ms = HAL_GetTick();
	  if ((uint32_t)(now_ms - last_hall_log_ms) >= 1000U) {
	      uint32_t m1_total;
	      uint32_t m2_total;
	      int32_t m1_position;
	      int32_t m2_position;

	      last_hall_log_ms += 1000U;

	      __disable_irq();
	      m1_total = motors[0].total_ticks;
	      m2_total = motors[1].total_ticks;
	      m1_position = motors[0].ticks;
	      m2_position = motors[1].ticks;
	      __enable_irq();

	      int length = snprintf(
	          uart_buffer,
	          sizeof(uart_buffer),
	          "%lu,%lu,%lu,%ld,%ld\r\n",
	          (unsigned long)now_ms,
	          (unsigned long)m1_total,
	          (unsigned long)m2_total,
	          (long)m1_position,
	          (long)m2_position
	      );

	      HAL_UART_Transmit(
	          &huart2,
	          (uint8_t *)uart_buffer,
	          (uint16_t)length,
	          HAL_MAX_DELAY
	      );
	  }

	  //Task 3: CAN transmit
	  uint32_t elapsed_timeCAN = elapsed(timer3_CAN_UDS);
	  if (elapsed_timeCAN - timer3_CAN_UDS.sec_marker >= 1000U){
		  uint8_t countData[8];
		  countData[0] = CAN_counter++;
	      countData[1] = 0;
		  countData[2] = 0;
		  countData[3] = 0;
		  countData[4] = 0;
		  countData[5] = 0;
		  countData[6] = 0;
		  countData[7] = 0;
		  HAL_StatusTypeDef txStatus =
			  HAL_FDCAN_AddMessageToTxFifoQ(
				  &hfdcan1,
				  &count,
				  countData
				  );
		  timer3_CAN_UDS.sec_marker += 1000U;

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
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV2;
  RCC_OscInitStruct.PLL.PLLN = 8;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV6;
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

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
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
  hfdcan1.Init.NominalPrescaler = 8;
  hfdcan1.Init.NominalSyncJumpWidth = 1;
  hfdcan1.Init.NominalTimeSeg1 = 11;
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

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};
  TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 0;
  htim1.Init.CounterMode = TIM_COUNTERMODE_CENTERALIGNED3;
  htim1.Init.Period = 4249;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim1) != HAL_OK)
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
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
  sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  sBreakDeadTimeConfig.OffStateRunMode = TIM_OSSR_DISABLE;
  sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
  sBreakDeadTimeConfig.LockLevel = TIM_LOCKLEVEL_OFF;
  sBreakDeadTimeConfig.DeadTime = 0;
  sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
  sBreakDeadTimeConfig.BreakPolarity = TIM_BREAKPOLARITY_HIGH;
  sBreakDeadTimeConfig.BreakFilter = 0;
  sBreakDeadTimeConfig.BreakAFMode = TIM_BREAK_AFMODE_INPUT;
  sBreakDeadTimeConfig.Break2State = TIM_BREAK2_DISABLE;
  sBreakDeadTimeConfig.Break2Polarity = TIM_BREAK2POLARITY_HIGH;
  sBreakDeadTimeConfig.Break2Filter = 0;
  sBreakDeadTimeConfig.Break2AFMode = TIM_BREAK_AFMODE_INPUT;
  sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
  if (HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig) != HAL_OK)
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

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_SlaveConfigTypeDef sSlaveConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_CENTERALIGNED3;
  htim2.Init.Period = 4249;
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
  if (HAL_TIM_PWM_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sSlaveConfig.SlaveMode = TIM_SLAVEMODE_RESET;
  sSlaveConfig.InputTrigger = TIM_TS_ITR0;
  if (HAL_TIM_SlaveConfigSynchro(&htim2, &sSlaveConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 2125;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.Pulse = 2125;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */
  HAL_TIM_MspPostInit(&htim2);

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
  TIM_SlaveConfigTypeDef sSlaveConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_CENTERALIGNED3;
  htim3.Init.Period = 4249;
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
  sSlaveConfig.SlaveMode = TIM_SLAVEMODE_RESET;
  sSlaveConfig.InputTrigger = TIM_TS_ITR0;
  if (HAL_TIM_SlaveConfigSynchro(&htim3, &sSlaveConfig) != HAL_OK)
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
  sConfigOC.Pulse = 2125;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */
  HAL_TIM_MspPostInit(&htim3);

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
  HAL_GPIO_WritePin(GPIOC, M1N_Pin|M2N_Pin|M3N_Pin|M4N_Pin
                          |M5N_Pin|M6N_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, M1P_Pin|M2P_Pin|M3P_Pin|M4P_Pin
                          |M5P_Pin|M6P_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : HALL_1A_Pin HALL_2A_Pin HALL_3A_Pin HALL_4A_Pin
                           HALL_5A_Pin HALL_6A_Pin */
  GPIO_InitStruct.Pin = HALL_1A_Pin|HALL_2A_Pin|HALL_3A_Pin|HALL_4A_Pin
                          |HALL_5A_Pin|HALL_6A_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : M1N_Pin M2N_Pin M3N_Pin M4N_Pin
                           M5N_Pin M6N_Pin */
  GPIO_InitStruct.Pin = M1N_Pin|M2N_Pin|M3N_Pin|M4N_Pin
                          |M5N_Pin|M6N_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : M1P_Pin M2P_Pin M3P_Pin M4P_Pin
                           M5P_Pin M6P_Pin */
  GPIO_InitStruct.Pin = M1P_Pin|M2P_Pin|M3P_Pin|M4P_Pin
                          |M5P_Pin|M6P_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : HALL_1B_Pin HALL_2B_Pin HALL_3B_Pin HALL_4B_Pin */
  GPIO_InitStruct.Pin = HALL_1B_Pin|HALL_2B_Pin|HALL_3B_Pin|HALL_4B_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : HALL_5B_Pin HALL_6B_Pin */
  GPIO_InitStruct.Pin = HALL_5B_Pin|HALL_6B_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* EXTI interrupt init*/
  HAL_NVIC_SetPriority(EXTI0_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI0_IRQn);

  HAL_NVIC_SetPriority(EXTI1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI1_IRQn);

  HAL_NVIC_SetPriority(EXTI2_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI2_IRQn);

  HAL_NVIC_SetPriority(EXTI3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI3_IRQn);

  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void BSP_PB_Callback(Button_TypeDef Button)
{
    if (Button == BUTTON_USER)
    {
        timer1 = start_timer();
        timer1_flag = 1U;
    }
}

// Table lookup keeps M1 and M2 Hall input handling consistent.
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
    for (uint8_t i = 0; i < NUM_MOTORS; i++) {
        if (GPIO_Pin == motors_hw[i].hall_a_pin) {
            motors[i].distance_ticks++;
            motors[i].total_ticks++;

            if ((motors_hw[i].hall_b_port->IDR & motors_hw[i].hall_b_pin) != 0U) {
                motors[i].ticks++;
            } else {
                motors[i].ticks--;
            }
            return;
        }
    }
    // Not one of the two motor Hall pins (e.g. user button EXTI) - ignore here,
    // BSP_PB_Callback handles the button separately.
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
