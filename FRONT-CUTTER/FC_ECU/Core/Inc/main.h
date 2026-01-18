/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
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
#define VISENSE_C_Pin GPIO_PIN_0
#define VISENSE_C_GPIO_Port GPIOC
#define VSENSE_C_Pin GPIO_PIN_1
#define VSENSE_C_GPIO_Port GPIOC
#define VISENSE_A_Pin GPIO_PIN_0
#define VISENSE_A_GPIO_Port GPIOA
#define VSENSE_A_Pin GPIO_PIN_1
#define VSENSE_A_GPIO_Port GPIOA
#define VISENSE_B_Pin GPIO_PIN_2
#define VISENSE_B_GPIO_Port GPIOA
#define VSENSE_B_Pin GPIO_PIN_3
#define VSENSE_B_GPIO_Port GPIOA
#define NLIN_A_Pin GPIO_PIN_7
#define NLIN_A_GPIO_Port GPIOA
#define NLIN_B_Pin GPIO_PIN_0
#define NLIN_B_GPIO_Port GPIOB
#define NLIN_C_Pin GPIO_PIN_1
#define NLIN_C_GPIO_Port GPIOB
#define VI_OUT_Pin GPIO_PIN_14
#define VI_OUT_GPIO_Port GPIOB
#define HIN_A_Pin GPIO_PIN_8
#define HIN_A_GPIO_Port GPIOA
#define HIN_B_Pin GPIO_PIN_9
#define HIN_B_GPIO_Port GPIOA
#define HIN_C_Pin GPIO_PIN_10
#define HIN_C_GPIO_Port GPIOA

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
