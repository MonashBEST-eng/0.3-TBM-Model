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
#define M1S_Pin GPIO_PIN_0
#define M1S_GPIO_Port GPIOA
#define M2S_Pin GPIO_PIN_1
#define M2S_GPIO_Port GPIOA
#define M6S_Pin GPIO_PIN_4
#define M6S_GPIO_Port GPIOA
#define M5S_Pin GPIO_PIN_6
#define M5S_GPIO_Port GPIOA
#define M1N_Pin GPIO_PIN_4
#define M1N_GPIO_Port GPIOC
#define M2N_Pin GPIO_PIN_5
#define M2N_GPIO_Port GPIOC
#define M1P_Pin GPIO_PIN_0
#define M1P_GPIO_Port GPIOB
#define M2P_Pin GPIO_PIN_1
#define M2P_GPIO_Port GPIOB
#define M3P_Pin GPIO_PIN_2
#define M3P_GPIO_Port GPIOB
#define M3S_Pin GPIO_PIN_10
#define M3S_GPIO_Port GPIOB
#define M4S_Pin GPIO_PIN_11
#define M4S_GPIO_Port GPIOB
#define M3N_Pin GPIO_PIN_6
#define M3N_GPIO_Port GPIOC
#define M4N_Pin GPIO_PIN_7
#define M4N_GPIO_Port GPIOC
#define M5N_Pin GPIO_PIN_8
#define M5N_GPIO_Port GPIOC
#define M6N_Pin GPIO_PIN_9
#define M6N_GPIO_Port GPIOC
#define T_SWDIO_Pin GPIO_PIN_13
#define T_SWDIO_GPIO_Port GPIOA
#define T_SWCLK_Pin GPIO_PIN_14
#define T_SWCLK_GPIO_Port GPIOA
#define T_SWO_Pin GPIO_PIN_3
#define T_SWO_GPIO_Port GPIOB
#define M4P_Pin GPIO_PIN_4
#define M4P_GPIO_Port GPIOB
#define M5P_Pin GPIO_PIN_5
#define M5P_GPIO_Port GPIOB
#define M6P_Pin GPIO_PIN_6
#define M6P_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
