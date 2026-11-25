/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
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

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32g4xx_hal.h"

#include "stm32g4xx_nucleo.h"
#include <stdio.h>

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim);

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define RCC_OSC32_OUT_Pin GPIO_PIN_14
#define RCC_OSC32_OUT_GPIO_Port GPIOC
#define RCC_OSC32_OUTC15_Pin GPIO_PIN_15
#define RCC_OSC32_OUTC15_GPIO_Port GPIOC
#define RCC_OSC_IN_Pin GPIO_PIN_0
#define RCC_OSC_IN_GPIO_Port GPIOF
#define RCC_OSC_OUT_Pin GPIO_PIN_1
#define RCC_OSC_OUT_GPIO_Port GPIOF
#define PIN_A_PWM_Pin GPIO_PIN_0
#define PIN_A_PWM_GPIO_Port GPIOC
#define GPIO_A1_Pin GPIO_PIN_1
#define GPIO_A1_GPIO_Port GPIOC
#define GPIO_A2_Pin GPIO_PIN_2
#define GPIO_A2_GPIO_Port GPIOC
#define PIN_D_PWM_Pin GPIO_PIN_3
#define PIN_D_PWM_GPIO_Port GPIOC
#define HALL_A1_Pin GPIO_PIN_0
#define HALL_A1_GPIO_Port GPIOA
#define HALL_A2_Pin GPIO_PIN_1
#define HALL_A2_GPIO_Port GPIOA
#define HALL_B2_Pin GPIO_PIN_4
#define HALL_B2_GPIO_Port GPIOA
#define HALL_B1_Pin GPIO_PIN_6
#define HALL_B1_GPIO_Port GPIOA
#define GPIO_B1_Pin GPIO_PIN_4
#define GPIO_B1_GPIO_Port GPIOC
#define GPIO_B2_Pin GPIO_PIN_5
#define GPIO_B2_GPIO_Port GPIOC
#define GPIO_C1_Pin GPIO_PIN_6
#define GPIO_C1_GPIO_Port GPIOC
#define GPIO_C2_Pin GPIO_PIN_7
#define GPIO_C2_GPIO_Port GPIOC
#define GPIO_D1_Pin GPIO_PIN_8
#define GPIO_D1_GPIO_Port GPIOC
#define GPIO_D2_Pin GPIO_PIN_9
#define GPIO_D2_GPIO_Port GPIOC
#define PIN_B_PWM_Pin GPIO_PIN_9
#define PIN_B_PWM_GPIO_Port GPIOA
#define PIN_C_PWM_Pin GPIO_PIN_10
#define PIN_C_PWM_GPIO_Port GPIOA
#define HALL_C1_Pin GPIO_PIN_11
#define HALL_C1_GPIO_Port GPIOA
#define HALL_C2_Pin GPIO_PIN_12
#define HALL_C2_GPIO_Port GPIOA
#define T_SWDIO_Pin GPIO_PIN_13
#define T_SWDIO_GPIO_Port GPIOA
#define T_SWCLK_Pin GPIO_PIN_14
#define T_SWCLK_GPIO_Port GPIOA
#define HALL_D1_Pin GPIO_PIN_15
#define HALL_D1_GPIO_Port GPIOA
#define T_SWO_Pin GPIO_PIN_3
#define T_SWO_GPIO_Port GPIOB
#define HALL_D2_Pin GPIO_PIN_8
#define HALL_D2_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
