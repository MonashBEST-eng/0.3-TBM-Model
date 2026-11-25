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
#include "stm32h7xx_hal.h"

#include "stm32h7xx_nucleo.h"
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
#define M1_A_Pin GPIO_PIN_2
#define M1_A_GPIO_Port GPIOE
#define M2_A_Pin GPIO_PIN_3
#define M2_A_GPIO_Port GPIOE
#define M1_B_Pin GPIO_PIN_4
#define M1_B_GPIO_Port GPIOE
#define M3_PWM_Pin GPIO_PIN_5
#define M3_PWM_GPIO_Port GPIOE
#define M4_PWM_Pin GPIO_PIN_6
#define M4_PWM_GPIO_Port GPIOE
#define M1_PWM_Pin GPIO_PIN_6
#define M1_PWM_GPIO_Port GPIOF
#define M2_B_Pin GPIO_PIN_7
#define M2_B_GPIO_Port GPIOF
#define M5_PWM_Pin GPIO_PIN_8
#define M5_PWM_GPIO_Port GPIOF
#define M6_PWM_Pin GPIO_PIN_9
#define M6_PWM_GPIO_Port GPIOF
#define ENC_5A_Pin GPIO_PIN_0
#define ENC_5A_GPIO_Port GPIOA
#define ENC_5B_Pin GPIO_PIN_1
#define ENC_5B_GPIO_Port GPIOA
#define ENC_2A_Pin GPIO_PIN_5
#define ENC_2A_GPIO_Port GPIOA
#define ENC_1A_Pin GPIO_PIN_9
#define ENC_1A_GPIO_Port GPIOE
#define ENC_1B_Pin GPIO_PIN_11
#define ENC_1B_GPIO_Port GPIOE
#define M6_A_Pin GPIO_PIN_13
#define M6_A_GPIO_Port GPIOE
#define M6_B_Pin GPIO_PIN_14
#define M6_B_GPIO_Port GPIOE
#define M2_PWM_Pin GPIO_PIN_15
#define M2_PWM_GPIO_Port GPIOB
#define ENC_4A_Pin GPIO_PIN_12
#define ENC_4A_GPIO_Port GPIOD
#define ENC_4B_Pin GPIO_PIN_13
#define ENC_4B_GPIO_Port GPIOD
#define ENC_6A_Pin GPIO_PIN_6
#define ENC_6A_GPIO_Port GPIOC
#define ENC_6B_Pin GPIO_PIN_7
#define ENC_6B_GPIO_Port GPIOC
#define M5_A_Pin GPIO_PIN_0
#define M5_A_GPIO_Port GPIOD
#define M5_B_Pin GPIO_PIN_1
#define M5_B_GPIO_Port GPIOD
#define M3_A_Pin GPIO_PIN_3
#define M3_A_GPIO_Port GPIOD
#define M3_B_Pin GPIO_PIN_4
#define M3_B_GPIO_Port GPIOD
#define M4_A_Pin GPIO_PIN_5
#define M4_A_GPIO_Port GPIOD
#define M4_B_Pin GPIO_PIN_6
#define M4_B_GPIO_Port GPIOD
#define ENC_2B_Pin GPIO_PIN_3
#define ENC_2B_GPIO_Port GPIOB
#define ENC_3A_Pin GPIO_PIN_4
#define ENC_3A_GPIO_Port GPIOB
#define ENC_3B_Pin GPIO_PIN_5
#define ENC_3B_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
