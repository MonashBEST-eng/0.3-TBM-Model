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
#include "mcp2515.h"
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* ==========================================================================
 * CAN COMMAND SCHEME - SCREW CONVEYER (this board)
 *
 * ID 0x080, DLC 1 unless noted:
 *   0x01  START
 *   0x02  STOP
 *   0x03  FORWARD   (deferred until motor reaches 0 speed if currently moving)
 *   0x04  REVERSE   (deferred until motor reaches 0 speed if currently moving)
 *   0x05  SET_SPEED (DLC 3: [0x05, speed_hi, speed_lo], 16-bit, 0-999)
 *
 * (LED_ON/LED_OFF commands removed - this board no longer has LD2
 * configured, PA5 is now SPI1_SCK instead)
 *
 * ID 0x010 - global safety ID shared across every node on the bus:
 *   0x01  EMERGENCY_STOP  - immediate, unconditional power cut (bypasses
 *                           the ramp/direction-safety logic entirely -
 *                           genuine emergencies need instant response)
 *   0x03  CLEAR EMERGENCY - re-arms the board, but does NOT auto-restart
 *                           the motor - an explicit START must follow
 * ==========================================================================*/
#define CAN_ID_SCREW_CONVEYER   0x080
#define CAN_ID_SAFETY           0x010

#define CMD_START       0x01
#define CMD_STOP        0x02
#define CMD_FORWARD     0x03
#define CMD_REVERSE     0x04
#define CMD_SET_SPEED   0x05

#define SAFETY_EMERGENCY_STOP    0x01
#define SAFETY_CLEAR_EMERGENCY   0x03

#define MOTOR_SPEED_MAX   999

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef hlpuart1;

SPI_HandleTypeDef hspi1;

TIM_HandleTypeDef htim1;

/* USER CODE BEGIN PV */

/* printf() retarget - redirects standard output to LPUART1 (tied to the
 * ST-LINK Virtual COM Port on this specific board - USART1 on PA2/PA3
 * turned out not to be available, this Nucleo variant uses LPUART1 for
 * the VCP instead), one character at a time. */
int _write(int file, char *ptr, int len)
{
    HAL_UART_Transmit(&hlpuart1, (uint8_t *)ptr, len, HAL_MAX_DELAY);
    return len;
}

CAN_Frame rxFrame;

/* Motor ramp/direction state - all non-blocking, advanced from the main
 * loop rather than inside a blocking while() loop, so incoming CAN frames
 * (especially EMERGENCY_STOP) are never left unprocessed while a ramp is
 * in progress. */
static volatile uint16_t motor_current_speed = 0;
static volatile uint16_t motor_target_speed  = 0;
static volatile uint8_t  motor_enabled       = 0;   /* mirrors EN pin state */

typedef enum { DIR_FORWARD, DIR_REVERSE } MotorDirection;
static volatile MotorDirection motor_direction         = DIR_FORWARD;
static volatile uint8_t        direction_change_pending = 0;
static volatile MotorDirection pending_direction;

/* Latched by EMERGENCY_STOP, only cleared by CLEAR EMERGENCY - matches the
 * same latch pattern used on the H7 (heartbeat_fault/estop_fault_led). */
static volatile uint8_t estop_active = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM1_Init(void);
static void MX_LPUART1_UART_Init(void);
static void MX_SPI1_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* ==========================================================================
 * LOW-LEVEL MOTOR CONTROL
 * ==========================================================================*/
void Motor_Start(void)
{
    HAL_GPIO_WritePin(EN_GPIO_Port, EN_Pin, GPIO_PIN_RESET);
}

void Motor_Stop(void)
{
    HAL_GPIO_WritePin(EN_GPIO_Port, EN_Pin, GPIO_PIN_SET);
}

void Motor_Forward(void)
{
    HAL_GPIO_WritePin(DIR_GPIO_Port, DIR_Pin, GPIO_PIN_SET);
}

void Motor_Reverse(void)
{
    HAL_GPIO_WritePin(DIR_GPIO_Port, DIR_Pin, GPIO_PIN_RESET);
}

/* Immediately snaps the PWM compare register and internal ramp state to a
 * given speed - no ramping, used for EMERGENCY_STOP and STOP where an
 * instant cut is exactly what's wanted, not a graceful ramp-down. */
static void Motor_SnapSpeed(uint16_t speed)
{
    if (speed > MOTOR_SPEED_MAX) speed = MOTOR_SPEED_MAX;
    motor_current_speed = speed;
    motor_target_speed  = speed;
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, speed);
}

/* ==========================================================================
 * NON-BLOCKING SPEED RAMP
 *
 * Replaces the original Motor_SetSpeed()'s blocking while()+HAL_Delay(10)
 * loop. Call this once per main loop iteration instead - it advances
 * current_speed one step toward target_speed at the same ~10ms-per-step
 * pace as the original, but without ever blocking, so CAN reception
 * (especially EMERGENCY_STOP) stays responsive throughout a ramp.
 *
 * Also handles the deferred direction-change safety: if a FORWARD/REVERSE
 * command arrived while the motor was moving, target_speed was already
 * set to 0 at that point (see CAN dispatch below) - once this ramp
 * actually reaches 0, the pending direction gets applied here. The motor
 * stays at 0 afterward; a fresh SET_SPEED is required to resume, rather
 * than assuming it should return to whatever speed it was at before the
 * direction change (safer default - no surprise resumption).
 * ==========================================================================*/
static void Motor_RampTick(void)
{
    static uint32_t last_step_tick = 0;

    if (HAL_GetTick() - last_step_tick < 10)
    {
        return;   /* not time for the next 1-unit step yet */
    }
    last_step_tick = HAL_GetTick();

    if (motor_current_speed == motor_target_speed)
    {
        /* Ramp settled - if a direction change was waiting for exactly
         * this (speed reached 0), apply it now. */
        if (direction_change_pending && motor_current_speed == 0)
        {
            if (pending_direction == DIR_FORWARD)
            {
                Motor_Forward();
            }
            else
            {
                Motor_Reverse();
            }
            motor_direction = pending_direction;
            direction_change_pending = 0;
        }
        return;
    }

    if (motor_current_speed < motor_target_speed)
    {
        motor_current_speed++;
    }
    else
    {
        motor_current_speed--;
    }

    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, motor_current_speed);
}

/* Requests a direction change. If the motor is already stopped (speed 0),
 * applies it immediately. Otherwise defers it - sets target_speed to 0 so
 * Motor_RampTick() ramps down first, then applies the direction once
 * speed genuinely reaches 0. This is the fix for the mechanical safety
 * concern flagged in an earlier draft of this firmware: switching
 * direction while still moving can damage the drivetrain. */
static void Motor_RequestDirection(MotorDirection dir)
{
    if (motor_current_speed == 0)
    {
        if (dir == DIR_FORWARD) Motor_Forward(); else Motor_Reverse();
        motor_direction = dir;
        direction_change_pending = 0;
    }
    else
    {
        pending_direction = dir;
        direction_change_pending = 1;
        motor_target_speed = 0;   /* Motor_RampTick() will ramp down, then apply */
    }
}

/* ==========================================================================
 * CAN COMMAND DISPATCH
 * ==========================================================================*/
static void handle_safety_frame(CAN_Frame *frame)
{
    if (frame->dlc < 1) return;

    if (frame->data[0] == SAFETY_EMERGENCY_STOP)
    {
        printf("SAFETY: EMERGENCY_STOP - cutting motor power immediately\r\n");
        estop_active = 1;
        motor_enabled = 0;
        Motor_Stop();
        Motor_SnapSpeed(0);              /* instant cut, no ramp */
        direction_change_pending = 0;    /* any pending direction change is moot now */
    }
    else if (frame->data[0] == SAFETY_CLEAR_EMERGENCY)
    {
        printf("SAFETY: CLEAR EMERGENCY - re-armed, motor stays off until START\r\n");
        estop_active = 0;
        /* Deliberately does NOT restart the motor - motor_enabled stays 0
         * until an explicit START command arrives. Auto-resuming a motor
         * right after an emergency clears would be a genuinely dangerous
         * default. */
    }
}

static void handle_screw_conveyer_frame(CAN_Frame *frame)
{
    if (frame->dlc < 1) return;

    /* Defense in depth: even though the GUI shouldn't be sending motor
     * commands while E-STOP is latched, this board doesn't blindly trust
     * that - any command other than what's already handled above is
     * ignored outright while estop_active is set. */
    if (estop_active)
    {
        printf("SCREW CONVEYER: command 0x%02X ignored - E-STOP active\r\n", frame->data[0]);
        return;
    }

    switch (frame->data[0])
    {
        case CMD_START:
            printf("SCREW CONVEYER: START\r\n");
            motor_enabled = 1;
            Motor_Start();
            break;

        case CMD_STOP:
            printf("SCREW CONVEYER: STOP\r\n");
            motor_enabled = 0;
            Motor_Stop();
            Motor_SnapSpeed(0);
            direction_change_pending = 0;
            break;

        case CMD_FORWARD:
            printf("SCREW CONVEYER: FORWARD requested%s\r\n",
                   motor_current_speed != 0 ? " (deferred - ramping down first)" : "");
            Motor_RequestDirection(DIR_FORWARD);
            break;

        case CMD_REVERSE:
            printf("SCREW CONVEYER: REVERSE requested%s\r\n",
                   motor_current_speed != 0 ? " (deferred - ramping down first)" : "");
            Motor_RequestDirection(DIR_REVERSE);
            break;

        case CMD_SET_SPEED:
            if (frame->dlc >= 3)
            {
                uint16_t speed = ((uint16_t)frame->data[1] << 8) | frame->data[2];
                if (speed > MOTOR_SPEED_MAX) speed = MOTOR_SPEED_MAX;
                printf("SCREW CONVEYER: SET_SPEED -> %u\r\n", speed);
                motor_target_speed = speed;   /* Motor_RampTick() ramps toward this */
            }
            else
            {
                printf("SCREW CONVEYER: SET_SPEED frame malformed (DLC=%d, need >=3)\r\n", frame->dlc);
            }
            break;

        default:
            printf("SCREW CONVEYER: unrecognized command byte 0x%02X - ignored\r\n", frame->data[0]);
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
  MX_TIM1_Init();
  MX_LPUART1_UART_Init();
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */
  HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);

  /* Motor starts stopped and disarmed - an explicit START command over
   * CAN is required before it will move at all. Direction defaults to
   * forward but has no effect until START + a nonzero SET_SPEED arrive. */
  Motor_Stop();
  motor_direction = DIR_FORWARD;
  Motor_Forward();

  printf("\r\n");
  printf("========================================\r\n");
  printf(" G4 SCREW CONVEYER - BOOT\r\n");
  printf("========================================\r\n");
  printf("SPI1 wiring expected:\r\n");
  printf("  SCK  -> PA5   (D13)\r\n");
  printf("  MISO -> PA6   (D12)\r\n");
  printf("  MOSI -> PA7   (D11)\r\n");
  printf("  CS   -> PC7   (D9)\r\n");
  printf("  INT  -> PA9   (D8, configured but unused - driver polls instead)\r\n");
  printf("SPI1 clock: 170MHz / 32 = 5.3125 MBit/s (MCP2515 max is 10MHz)\r\n");
  printf("----------------------------------------\r\n");

  printf("Initializing MCP2515...\r\n");
  HAL_StatusTypeDef mcp_init_status = MCP2515_Init(&hspi1);

  /* DIAGNOSTIC: raw register read regardless of init outcome - shows
   * exactly what's coming back over SPI, plus whether the SPI
   * transaction itself actually completed (a 0x00 could mean "the chip
   * genuinely responded with 0" OR "the SPI transaction timed out and
   * rx[] was never touched, still holding its zero-initialized value" -
   * these look identical without checking the transaction status too). */
  {
      printf("  [diag] raw CANSTAT reads (3x): ");
      for (uint8_t i = 0; i < 3; i++)
      {
          uint8_t raw = MCP2515_ReadRegister(MCP2515_CANSTAT);
          HAL_StatusTypeDef spi_status = MCP2515_GetLastSpiStatus();
          printf("0x%02X(%s) ", raw,
                 spi_status == HAL_OK      ? "OK" :
                 spi_status == HAL_TIMEOUT ? "TIMEOUT" :
                 spi_status == HAL_ERROR   ? "ERROR" : "BUSY");
      }
      printf("\r\n  [diag] (0xFF/0x00 every time = chip not responding at all;\r\n"
             "          changing/random values = noise or a clock issue;\r\n"
             "          TIMEOUT status = SPI transaction itself never completed)\r\n");
  }

  if (mcp_init_status != HAL_OK)
  {
      printf("MCP2515 init FAILED - check SPI wiring/power\r\n");
      while (1)
      {
          /* No LED on this board anymore - halt here, PuTTY output above
           * is the diagnostic signal now. */
      }
  }
  printf("MCP2515 init OK - Normal mode\r\n");

  /* DIAGNOSTIC: confirm the chip genuinely reports Normal mode after
   * init, not just that the init call returned HAL_OK. CANSTAT's top 3
   * bits are the operating mode - 0x00 = Normal. */
  {
      uint8_t canstat = MCP2515_ReadRegister(MCP2515_CANSTAT);
      printf("  [diag] CANSTAT = 0x%02X (mode bits = 0x%02X, 0x00 = Normal)\r\n",
             canstat, canstat & 0xE0);
  }

  /* MCP2515 loopback self-test - same validator used on the H7 and
   * L432KC. Puts the chip in internal Loopback mode, sends a known test
   * frame, verifies it comes back byte-for-byte, then restores Normal
   * mode regardless of outcome - same as the other boards. */
  printf("Running loopback self-test...\r\n");
  if (MCP2515_LoopbackSelfTest() == HAL_OK)
  {
      printf("LOOPBACK TEST: PASS - SPI link + MCP2515 driver working correctly\r\n");
  }
  else
  {
      printf("LOOPBACK TEST: FAIL - check wiring (SCK/MISO/MOSI/CS) and MCP2515 power\r\n");
      while (1)
      {
          /* No LED on this board anymore - halt here. */
      }
  }

  printf("----------------------------------------\r\n");
  printf("Ready - listening on CAN ID 0x%03X (screw conveyer) and 0x%03X (safety)\r\n",
         CAN_ID_SCREW_CONVEYER, CAN_ID_SAFETY);
  printf("Motor: stopped, disarmed - waiting for START command\r\n");
  printf("========================================\r\n\r\n");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    if (MCP2515_CheckReceive())
    {
        MCP2515_ReadMessage(&rxFrame);

        printf("CAN RX: ID=0x%03lX DLC=%d Data:", rxFrame.id, rxFrame.dlc);
        for (uint8_t i = 0; i < rxFrame.dlc; i++)
        {
            printf(" %02X", rxFrame.data[i]);
        }
        printf("\r\n");

        if (rxFrame.id == CAN_ID_SAFETY)
        {
            handle_safety_frame(&rxFrame);
        }
        else if (rxFrame.id == CAN_ID_SCREW_CONVEYER)
        {
            handle_screw_conveyer_frame(&rxFrame);
        }
    }

    Motor_RampTick();
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
  * @brief LPUART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_LPUART1_UART_Init(void)
{

  /* USER CODE BEGIN LPUART1_Init 0 */

  /* USER CODE END LPUART1_Init 0 */

  /* USER CODE BEGIN LPUART1_Init 1 */

  /* USER CODE END LPUART1_Init 1 */
  hlpuart1.Instance = LPUART1;
  hlpuart1.Init.BaudRate = 115200;
  hlpuart1.Init.WordLength = UART_WORDLENGTH_8B;
  hlpuart1.Init.StopBits = UART_STOPBITS_1;
  hlpuart1.Init.Parity = UART_PARITY_NONE;
  hlpuart1.Init.Mode = UART_MODE_TX_RX;
  hlpuart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  hlpuart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  hlpuart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  hlpuart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&hlpuart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&hlpuart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN LPUART1_Init 2 */

  /* USER CODE END LPUART1_Init 2 */

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
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_32;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

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
  htim1.Init.Prescaler = 169;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 999;
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
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
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
  HAL_TIM_MspPostInit(&htim1);

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
  HAL_GPIO_WritePin(GPIOB, EN_Pin|DIR_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(MCP2515_CS_GPIO_Port, MCP2515_CS_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin : B1_Pin */
  GPIO_InitStruct.Pin = B1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(B1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : EN_Pin DIR_Pin */
  GPIO_InitStruct.Pin = EN_Pin|DIR_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : MCP2515_CS_Pin */
  GPIO_InitStruct.Pin = MCP2515_CS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(MCP2515_CS_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : MCP2515_INT_Pin */
  GPIO_InitStruct.Pin = MCP2515_INT_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(MCP2515_INT_GPIO_Port, &GPIO_InitStruct);

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
