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

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

// --- Stewart Platform Motor State typedef ---
typedef enum{
	SLEEP_STANDBY,
    FORWARD_STANDBY,
    BACKWARD_STANDBY,
    FORWARD,
    BACKWARD,
    BRAKE,
    HOMING}          // open-loop retract to end stops (used to recover from a fault)
stewart_state;
// --- command direction typedef ---
typedef enum{
	GO,
	REVERSE,
} command_direction;
// ---  Motor structure define ---
typedef struct{
	// bare bones defines
	TIM_HandleTypeDef *timer;        // PWM timer
	uint32_t channel;                // PWM channel
	GPIO_TypeDef *gpioportA;
	uint16_t GPIOPinA;
	GPIO_TypeDef *gpioportB;
	uint16_t GPIOPinB;

	// encoder feedback (replaces hall EXTI counting)
	TIM_HandleTypeDef *enc_timer;    // encoder timer (TIM4 / TIM8)
	uint16_t enc_last;               // last raw counter value
	int32_t position_ticks;          // signed position (+ extending)
	int32_t speed_ticks;             // ticks since last speed update (signed)

	// after encoder feedback
	float position_mm;
	uint16_t speed;
	uint8_t direction;
} motor;

// Result output format for findmin
typedef struct{
	uint32_t idx;
	uint32_t value;
} minResult;

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define ACTUATOR_COUNT 2U

// --- Timing ---
#define CTRL_PERIOD_MS   10U    // encoder read + sync loop
#define PRINT_PERIOD_MS  100U   // UART print + speed window

// --- Sync controller (tune these) ---
#define BASE_DUTY  2800         // nominal compare (ARR = 3399), headroom for the lagging motor
#define DUTY_MIN    600         // don't let a motor stall
#define DUTY_MAX   3230         // ~95%: leaves PWM off-time for the driver's high side
#define KP          1.5f         // duty counts per tick of position error
#define KI         0.01f         // duty counts added per tick of error, every 10 ms
#define KD         0.0f         // leave at 0 to start (encoder ticks make D noisy)
#define I_LIMIT  800.0f         // max duty the I term can contribute (anti-windup)

// --- Safety ---
#define ERR_LIMIT   10000       // ticks: if the actuators get this far apart, stop both

// --- Encoder <-> motor mapping (match whatever you found works) ---
// Each motor must read the encoder on ITS OWN actuator.
#define M1_ENC_TIMER  htim8     // encoder on the actuator driven by TIM2 CH3
#define M2_ENC_TIMER  htim4     // encoder on the actuator driven by TIM3 CH1

// --- Encoder direction fix ---
// If an actuator counts NEGATIVE while extending, set its entry to 1.
#define ENC1_INVERT  0          // M1
#define ENC2_INVERT  0          // M2 (TIM4 counts backwards)
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
DMA_HandleTypeDef hdma_usart2_tx;

/* USER CODE BEGIN PV */
// states/buttons
static stewart_state motor_state = SLEEP_STANDBY;
static volatile uint8_t button_event = 0U;
//motors
static motor h_bridge[ACTUATOR_COUNT] = {
		{   // M1
	        .timer = &htim3,              // PB4  = M1_PWM
	        .channel = TIM_CHANNEL_1,
	        .gpioportA = M1_A_GPIO_Port,
	        .GPIOPinA = M1_A_Pin,
	        .gpioportB = M1_B_GPIO_Port,
	        .GPIOPinB = M1_B_Pin,
	        .enc_timer = &M1_ENC_TIMER
	    },
	    {   // M2
	        .timer = &htim2,              // PB10 = M2_pwm
	        .channel = TIM_CHANNEL_3,
	        .gpioportA = M2_a_GPIO_Port,
	        .GPIOPinA = M2_a_Pin,
	        .gpioportB = M2_b_GPIO_Port,
	        .GPIOPinB = M2_b_Pin,
	        .enc_timer = &M2_ENC_TIMER
	    }
};

// Speeds array
volatile uint32_t speeds[ACTUATOR_COUNT];


//print uart data variables
static uint32_t last_uart_print_ms = 0;

// latest sync error + duties (for printing / tuning)
static int32_t sync_error = 0;
static int32_t duty_cmd[ACTUATOR_COUNT] = {BASE_DUTY, BASE_DUTY};

// PID state
static float   i_acc    = 0.0f;     // integral term, in duty counts
static int32_t err_prev = 0;
static uint8_t fault    = 0U;       // 1 = stopped because actuators got too far apart


/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_FDCAN1_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM8_Init(void);
static void MX_USART2_UART_Init(void);
/* USER CODE BEGIN PFP */
void move_all_generic(command_direction);
void brake();
void sleep();
minResult simple_findmin(const volatile uint32_t arr[], uint32_t length);
static void update_encoders(void);
static void sync_actuators(void);
static int32_t clamp_i32(int32_t x, int32_t lo, int32_t hi);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
void move_all_generic(command_direction direction){
	// fresh PID state each move (err sign flips between extend and retract)
	i_acc = 0.0f;
	err_prev = 0;

	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];

		// every move starts both motors at the same duty; sync adjusts from there
		__HAL_TIM_SET_COMPARE(m->timer, m->channel, BASE_DUTY);

		if(direction == GO){
			    m->gpioportA->BSRR = (uint32_t)m->GPIOPinA;          // Set A
			    m->gpioportB->BSRR = (uint32_t)m->GPIOPinB << 16U;  // Reset B
			}
		if(direction == REVERSE){
				m->gpioportA->BSRR = (uint32_t)m->GPIOPinA << 16U;  // Reset A
			    m->gpioportB->BSRR = (uint32_t)m->GPIOPinB;          // Set B
			}
			HAL_TIM_PWM_Start(m->timer, m->channel);
	}
	HAL_TIM_Base_Start(&htim1);
}

void sleep(){
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];
		HAL_TIM_PWM_Stop(m->timer,m->channel);
	}
	HAL_TIM_Base_Stop(&htim1);
}

void brake(){
	for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
		motor *m = &h_bridge[i];
			    m->gpioportA->BSRR = (uint32_t)m->GPIOPinA; // Set A
			    m->gpioportB->BSRR = (uint32_t)m->GPIOPinB; // Set B
	}
}

minResult simple_findmin(const volatile uint32_t arr[], uint32_t length){
	minResult min = {
			.idx = 0,
			.value = arr[0]
	};

	for(uint32_t i=1; i<length;i++){
		if(arr[i]<min.value){
			min.idx = i;
			min.value = arr[i];
		}
	}
	return min;
}

static void update_encoders(void){
    for (uint8_t i = 0; i < ACTUATOR_COUNT; i++){
        motor *m = &h_bridge[i];
        uint16_t now = __HAL_TIM_GET_COUNTER(m->enc_timer);
        int16_t delta = (int16_t)(now - m->enc_last);  // handles 16-bit wraparound
        m->enc_last = now;

        if ((i == 0 && ENC1_INVERT) || (i == 1 && ENC2_INVERT)){
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

// Position sync: slow the actuator that's ahead, speed up the one behind
// Position sync: slow the actuator that's ahead, speed up the one behind (PID + anti-windup)
static void sync_actuators(void){
	if (motor_state != FORWARD && motor_state != BACKWARD) return;

	int32_t raw = h_bridge[0].position_ticks - h_bridge[1].position_ticks;  // >0 = M1 ahead extending

	// Safety: actuators too far apart -> stop both
	if (raw > ERR_LIMIT || raw < -ERR_LIMIT){
		sleep();
		motor_state = SLEEP_STANDBY;
		fault = 1U;
		return;
	}

	int32_t err = (motor_state == BACKWARD) ? -raw : raw;   // retracting: "ahead" = smaller position

	// P and D
	float p_term = KP * (float)err;
	float d_term = KD * (float)(err - err_prev);
	err_prev = err;

	// Tentative integral (hard cap kept as a backstop)
	float i_new = i_acc + KI * (float)err;
	if (i_new >  I_LIMIT) i_new =  I_LIMIT;
	if (i_new < -I_LIMIT) i_new = -I_LIMIT;

	// Would this output saturate either motor?
	int32_t u_try  = (int32_t)(p_term + i_new + d_term);
	int32_t d0_try = BASE_DUTY - u_try;
	int32_t d1_try = BASE_DUTY + u_try;
	uint8_t sat_pos = (d0_try < DUTY_MIN) || (d1_try > DUTY_MAX);   // pushing "slow M1 / speed M2" too hard
	uint8_t sat_neg = (d0_try > DUTY_MAX) || (d1_try < DUTY_MIN);   // pushing "speed M1 / slow M2" too hard

	// Anti-windup (conditional integration): only accept the new integral
	// if it doesn't drive the output further into saturation
	if (!((sat_pos && err > 0) || (sat_neg && err < 0))){
		i_acc = i_new;
	}

	int32_t u  = (int32_t)(p_term + i_acc + d_term);
	int32_t d0 = clamp_i32(BASE_DUTY - u, DUTY_MIN, DUTY_MAX);   // slow the leader
	int32_t d1 = clamp_i32(BASE_DUTY + u, DUTY_MIN, DUTY_MAX);   // speed up the lagger

	sync_error  = err;
	duty_cmd[0] = d0;
	duty_cmd[1] = d1;

	__HAL_TIM_SET_COMPARE(h_bridge[0].timer, h_bridge[0].channel, (uint32_t)d0);
	__HAL_TIM_SET_COMPARE(h_bridge[1].timer, h_bridge[1].channel, (uint32_t)d1);
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
  MX_DMA_Init();
  MX_FDCAN1_Init();
  MX_TIM1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_TIM4_Init();
  MX_TIM8_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
  HAL_TIM_Encoder_Start(&htim4, TIM_CHANNEL_ALL);
  HAL_TIM_Encoder_Start(&htim8, TIM_CHANNEL_ALL);
  for (uint8_t i = 0; i < ACTUATOR_COUNT; i++)
      h_bridge[i].enc_last = __HAL_TIM_GET_COUNTER(h_bridge[i].enc_timer);
  /* USER CODE END 2 */

  /* Initialize leds */
  BSP_LED_Init(LED_GREEN);

  /* Initialize USER push-button, will be used to trigger an interrupt each time it's pressed.*/
  BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  minResult current_minSpeed = {0};
  uint32_t last_enc_ms = 0;

  // Banner + 4 placeholder lines. Last line has no \r\n so the cursor sits on it.
  printf("\r\nSTM started/reset\r\n"
         "M1 speed=0  M2 speed=0\r\n"
         "Min speed=0  Motor index=0\r\n"
         "M1 pos=0  M2 pos=0\r\n"
         "err=0  I=0  M1 duty=0  M2 duty=0");
  fflush(stdout);

  while (1)
  {
	  uint32_t now = HAL_GetTick();

	  //------------------- Read encoders + sync every 10 ms ----------------------
	  if ((uint32_t)(now - last_enc_ms) >= CTRL_PERIOD_MS)
	  {
		  last_enc_ms = now;
		  update_encoders();
		  sync_actuators();
	  }

	  //------------------- Print every 100 ms (updates the same 4 lines) ----------------------
	  if ((uint32_t)(now - last_uart_print_ms) >= PRINT_PERIOD_MS)
	  {
		  last_uart_print_ms = now;

		  // grab speed (ticks per 100 ms, signed) and reset for the next window
		  int32_t s0 = h_bridge[0].speed_ticks;
		  int32_t s1 = h_bridge[1].speed_ticks;
		  h_bridge[0].speed_ticks = 0;
		  h_bridge[1].speed_ticks = 0;

		  // findmin compares magnitudes, so it works extending or retracting
		  speeds[0] = (uint32_t)((s0 < 0) ? -s0 : s0);
		  speeds[1] = (uint32_t)((s1 < 0) ? -s1 : s1);
		  current_minSpeed = simple_findmin(speeds, ACTUATOR_COUNT);

		  // cursor is on the last line -> go up 3, rewrite all 4 lines
		  printf("\033[3A"
		         "\r\033[2K"
		         "M1 speed=%6ld  M2 speed=%6ld\r\n"
		         "\r\033[2K"
		         "Min speed=%6lu  Motor index=%lu\r\n"
		         "\r\033[2K"
		         "M1 pos=%8ld  M2 pos=%8ld\r\n"
		         "\r\033[2K"
		         "err=%6ld  I=%5ld  M1 duty=%4ld  M2 duty=%4ld  %s",
		         (long)s0,
		         (long)s1,
		         (unsigned long)current_minSpeed.value,
		         (unsigned long)current_minSpeed.idx,
		         (long)h_bridge[0].position_ticks,
		         (long)h_bridge[1].position_ticks,
		         (long)sync_error,
		         (long)i_acc,
		         (long)duty_cmd[0],
		         (long)duty_cmd[1],
		         (motor_state == HOMING) ? "HOMING (press when both retracted)" :
		         fault ? "FAULT: press to home" : "");
		  fflush(stdout);
	  }

	  //------------------- Button: step through motor states ----------------------
	  if (button_event)
	  {
	      button_event = 0U;

	      if (fault && motor_state == SLEEP_STANDBY)
	      {
	          // after a fault: retract both open-loop until they sit on their end stops
	          motor_state = HOMING;
	          move_all_generic(REVERSE);
	      }
	      else if (motor_state == HOMING)
	      {
	          // both fully retracted: stop and call this position zero
	          sleep();
	          h_bridge[0].position_ticks = 0;
	          h_bridge[1].position_ticks = 0;
	          fault = 0U;
	          motor_state = SLEEP_STANDBY;
	      }
	      else switch (motor_state)
	      {
	          case SLEEP_STANDBY:
	              motor_state = FORWARD;
	              move_all_generic(GO);
	              break;

	          case FORWARD:
	              motor_state = BRAKE;
	              brake();
	              break;

	          case BRAKE:
	              motor_state = BACKWARD;
	              move_all_generic(REVERSE);
	              break;

	          case BACKWARD:
	          default:
	              motor_state = SLEEP_STANDBY;
	              sleep();
	              break;
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
  hfdcan1.Init.NominalPrescaler = 16;
  hfdcan1.Init.NominalSyncJumpWidth = 1;
  hfdcan1.Init.NominalTimeSeg1 = 1;
  hfdcan1.Init.NominalTimeSeg2 = 1;
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

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 0;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 3399;
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

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_SlaveConfigTypeDef sSlaveConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 3399;
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
  sConfigOC.Pulse = 3000;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
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
  sConfigOC.Pulse = 3000;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
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
  sConfig.IC1Polarity = TIM_ICPOLARITY_FALLING;
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
  * Enable DMA controller clock
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMAMUX1_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA1_Channel1_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Channel1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);

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
  HAL_GPIO_WritePin(GPIOA, M1_A_Pin|M1_B_Pin|M2_a_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(M2_b_GPIO_Port, M2_b_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : M1_A_Pin M1_B_Pin M2_a_Pin */
  GPIO_InitStruct.Pin = M1_A_Pin|M1_B_Pin|M2_a_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : M2_b_Pin */
  GPIO_InitStruct.Pin = M2_b_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(M2_b_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

int __io_putchar(int ch)
{
    HAL_UART_Transmit(&huart2, (uint8_t *)&ch, 1, HAL_MAX_DELAY);
    return ch;
}


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
