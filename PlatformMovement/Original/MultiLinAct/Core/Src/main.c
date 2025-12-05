/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Stewart Platform ECU - Controls 2 linear actuators via GPIO
  *                   Works with FullSystemPPECU.py over USB CDC
  ******************************************************************************
*/
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "usbd_cdc_if.h"
#include <string.h>
#include <stdio.h>
#include <stdbool.h>
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
FDCAN_HandleTypeDef hfdcan1;

TIM_HandleTypeDef htim2;

/* USER CODE BEGIN PV */
typedef struct {
    int8_t   dir;          // -1 = retract, +1 = extend, 0 = no move
    uint32_t duration_ms;
} MoveCmd_t;

MoveCmd_t cmd[2] = {{0,0}, {0,0}};
volatile bool prepared = false;
volatile bool motion_active = false;
uint32_t motion_start_tick = 0;
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
void CDC_ProcessCommand(uint8_t* Buf, uint32_t Len);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
void CDC_ProcessCommand(uint8_t* Buf, uint32_t Len)
{
    if (Len < 4) return;

    char* str = (char*)Buf;

    // PREPARE d1 t1 d2 t2
    if (strncmp(str, "PREPARE", 7) == 0)
    {
        int d1, d2;
        uint32_t t1, t2;
        if (sscanf(str + 7, " %d %u %d %u", &d1, &t1, &d2, &t2) == 4)
        {
            cmd[0].dir = d1; cmd[0].duration_ms = t1;
            cmd[1].dir = d2; cmd[1].duration_ms = t2;

            // CHANGE: Removed Sleep(0) and Control() from here to sync start on START

            prepared = true;
            CDC_Transmit_FS((uint8_t*)"PREPARED\r\n", 10);
        }
    }
    // START
    else if (strncmp(str, "START", 5) == 0 && prepared)
    {
        // CHANGE: Moved awake and direction set here for sync start
        Motor1_Sleep(0);
        Motor2_Sleep(0);
        Motor1_Control(cmd[0].dir > 0 ? MOTOR_STATE_FORWARD : (cmd[0].dir < 0 ? MOTOR_STATE_REVERSE : MOTOR_STATE_COAST));
        Motor2_Control(cmd[1].dir > 0 ? MOTOR_STATE_FORWARD : (cmd[1].dir < 0 ? MOTOR_STATE_REVERSE : MOTOR_STATE_COAST));

        if (cmd[0].duration_ms == 0 && cmd[1].duration_ms == 0)
        {
            CDC_Transmit_FS((uint8_t*)"DONE\r\n", 6);
            // CHANGE: Sleep after zero-duration "move"
            Motor1_Sleep(1);
            Motor2_Sleep(1);
        }
        else
        {
            motion_start_tick = HAL_GetTick();
            motion_active = true;
            CDC_Transmit_FS((uint8_t*)"MOVING\r\n", 8);
        }
    }
    // Emergency STOP
    else if (strncmp(str, "STOP", 4) == 0)
    {
        // CHANGE: Use COAST instead of BRAKE to turn pins off
        Motor1_Control(MOTOR_STATE_COAST);
        Motor2_Control(MOTOR_STATE_COAST);
        // CHANGE: Sleep after stop
        Motor1_Sleep(1);
        Motor2_Sleep(1);
        motion_active = false;
        prepared = false;
        CDC_Transmit_FS((uint8_t*)"STOPPED\r\n", 9);
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
  MX_TIM2_Init();
  MX_USB_Device_Init();
  /* USER CODE BEGIN 2 */
  // Start with drivers asleep and coasting
  Motor1_Sleep(1);
  Motor2_Sleep(1);

  CDC_Transmit_FS((uint8_t*)"ECU READY\r\n", 11);
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    if (motion_active)
    {
        uint32_t elapsed = HAL_GetTick() - motion_start_tick;

        if (cmd[0].duration_ms > 0 && elapsed >= cmd[0].duration_ms)
            // CHANGE: Use COAST instead of BRAKE to turn pins off
            Motor1_Control(MOTOR_STATE_COAST);

        if (cmd[1].duration_ms > 0 && elapsed >= cmd[1].duration_ms)
            // CHANGE: Use COAST instead of BRAKE to turn pins off
            Motor2_Control(MOTOR_STATE_COAST);

        bool all_done = (cmd[0].duration_ms == 0 || elapsed >= cmd[0].duration_ms) &&
                        (cmd[1].duration_ms == 0 || elapsed >= cmd[1].duration_ms);

        if (all_done || elapsed > 10000)  // 10s safety timeout
        {
            motion_active = false;
            prepared = false;
            CDC_Transmit_FS((uint8_t*)"DONE\r\n", 6);
            // CHANGE: Sleep after done to fully disable drivers
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
        case MOTOR_STATE_FORWARD: HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_SET);
                                  HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_RESET); break;
        case MOTOR_STATE_REVERSE: HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_RESET);
                                  HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_SET);   break;
        case MOTOR_STATE_BRAKE:   HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_SET);
                                  HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_SET);   break;
        default:                  HAL_GPIO_WritePin(H1_FWD_GPIO_Port, H1_FWD_Pin, GPIO_PIN_RESET);
                                  HAL_GPIO_WritePin(H1_REV_GPIO_Port, H1_REV_Pin, GPIO_PIN_RESET); break;
    }
}

void Motor2_Control(Motor_State_t state)
{
    switch (state)
    {
        case MOTOR_STATE_FORWARD: HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_SET);
                                  HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_RESET); break;
        case MOTOR_STATE_REVERSE: HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_RESET);
                                  HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_SET);   break;
        case MOTOR_STATE_BRAKE:   HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_SET);
                                  HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_SET);   break;
        default:                  HAL_GPIO_WritePin(H2_FWD_GPIO_Port, H2_FWD_Pin, GPIO_PIN_RESET);
                                  HAL_GPIO_WritePin(H2_REV_GPIO_Port, H2_REV_Pin, GPIO_PIN_RESET); break;
    }
}

void Motor1_Sleep(uint8_t sleep)
{
    HAL_GPIO_WritePin(H1_SLEEP_GPIO_Port, H1_SLEEP_Pin, sleep ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

void Motor2_Sleep(uint8_t sleep)
{
    HAL_GPIO_WritePin(H2_SLEEP_GPIO_Port, H2_SLEEP_Pin, sleep ? GPIO_PIN_RESET : GPIO_PIN_SET);
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
