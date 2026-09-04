/*
 * mcp2515.h
 *
 * MCP2515 CAN Controller Driver — STM32 HAL SPI
 * Configured for: 8 MHz MCP2515 oscillator, 500 kbps CAN bitrate
 *
 * Wiring assumed (Cortex-M7, NUCLEO-H755ZI-Q, SPI1):
 *   SCK  -> PA5  (D13)
 *   MISO -> PB4  (D12)
 *   MOSI -> PB5  (D11)
 *   CS   -> PD14 (D10)  — software-controlled GPIO output, labeled MCP2515_CS in CubeMX
 *   INT  -> PD13 (D28)  — EXTI13, falling edge, labeled MCP2515_INT in CubeMX
 *
 *  NOTE: Update MCP2515_CS_GPIO_Port / MCP2515_CS_Pin below if your CubeMX
 *  user labels differ from what's used here (they come from main.h).
 */

#ifndef MCP2515_H
#define MCP2515_H

#include "main.h"     /* brings in HAL types + CubeMX-generated pin/port defines */
#include <stdint.h>

/* ==========================================================================
 * SPI INSTRUCTION SET (MCP2515 datasheet, Table 12-1)
 * ==========================================================================*/
#define MCP2515_INSTR_RESET        0xC0
#define MCP2515_INSTR_READ         0x03
#define MCP2515_INSTR_WRITE        0x02
#define MCP2515_INSTR_RTS          0x80   /* OR with (TXB0=0x01, TXB1=0x02, TXB2=0x04) */
#define MCP2515_INSTR_READ_STATUS  0xA0
#define MCP2515_INSTR_RX_STATUS    0xB0
#define MCP2515_INSTR_BIT_MODIFY   0x05

/* ==========================================================================
 * REGISTER ADDRESSES (partial — the ones this driver actually touches)
 * ==========================================================================*/
#define MCP2515_CANSTAT    0x0E
#define MCP2515_CANCTRL    0x0F
#define MCP2515_CNF3       0x28
#define MCP2515_CNF2       0x29
#define MCP2515_CNF1       0x2A
#define MCP2515_CANINTE    0x2B
#define MCP2515_CANINTF    0x2C
#define MCP2515_EFLG       0x2D

#define MCP2515_TXB0CTRL   0x30
#define MCP2515_TXB0SIDH   0x31
#define MCP2515_TXB0SIDL   0x32
#define MCP2515_TXB0EID8   0x33
#define MCP2515_TXB0EID0   0x34
#define MCP2515_TXB0DLC    0x35
#define MCP2515_TXB0D0     0x36

#define MCP2515_RXB0CTRL   0x60
#define MCP2515_RXB0SIDH   0x61
#define MCP2515_RXB0SIDL   0x62
#define MCP2515_RXB0EID8   0x63
#define MCP2515_RXB0EID0   0x64
#define MCP2515_RXB0DLC    0x65
#define MCP2515_RXB0D0     0x66

#define MCP2515_RXB1CTRL   0x70
#define MCP2515_RXB1SIDH   0x71

/* Receive filter/mask — set to "accept all" during init */
#define MCP2515_RXM0SIDH   0x20
#define MCP2515_RXM1SIDH   0x24

/* ==========================================================================
 * CANCTRL / CANSTAT MODE BITS (bits 7:5)
 * ==========================================================================*/
#define MCP2515_MODE_NORMAL      0x00
#define MCP2515_MODE_SLEEP       0x20
#define MCP2515_MODE_LOOPBACK    0x40
#define MCP2515_MODE_LISTENONLY  0x60
#define MCP2515_MODE_CONFIG      0x80
#define MCP2515_MODE_MASK        0xE0

/* CANINTF flag bits */
#define MCP2515_CANINTF_RX0IF   0x01
#define MCP2515_CANINTF_RX1IF   0x02
#define MCP2515_CANINTF_TX0IF   0x04
#define MCP2515_CANINTF_ERRIF   0x20
#define MCP2515_CANINTF_MERRF   0x80

/* RXB0CTRL: 0x60 = turn off filtering, receive any message (standard + extended) */
#define MCP2515_RXB0CTRL_RXM_ANY  0x60
#define MCP2515_RXB0CTRL_BUKT     0x04   /* rollover to RXB1 if RXB0 full */

/* Bit timing config for 8 MHz oscillator @ 500 kbps
 * (standard values used across most MCP2515 driver libraries) */
#define MCP2515_CNF1_8MHZ_500KBPS   0x00
#define MCP2515_CNF2_8MHZ_500KBPS   0x90
#define MCP2515_CNF3_8MHZ_500KBPS   0x02

/* ==========================================================================
 * CAN FRAME STRUCT
 * ==========================================================================*/
typedef struct {
    uint32_t id;        /* 11-bit standard or 29-bit extended ID */
    uint8_t  ext;        /* 1 = extended (29-bit) ID, 0 = standard (11-bit) */
    uint8_t  rtr;         /* 1 = remote request frame, 0 = data frame */
    uint8_t  dlc;          /* data length, 0-8 */
    uint8_t  data[8];
} CAN_Frame;

/* ==========================================================================
 * PIN MACROS — update these if your CubeMX user labels differ
 * ==========================================================================*/
#define MCP2515_CS_LOW()   HAL_GPIO_WritePin(MCP2515_CS_GPIO_Port, MCP2515_CS_Pin, GPIO_PIN_RESET)
#define MCP2515_CS_HIGH()  HAL_GPIO_WritePin(MCP2515_CS_GPIO_Port, MCP2515_CS_Pin, GPIO_PIN_SET)

/* ==========================================================================
 * PUBLIC API
 * ==========================================================================*/

/* Call once at startup, after HAL/SPI1 init. Returns HAL_OK if the MCP2515
 * responds correctly and enters Normal mode. */
HAL_StatusTypeDef MCP2515_Init(SPI_HandleTypeDef *hspi);

/* Low-level register access (exposed in case you need to poke a register
 * this driver doesn't have a dedicated helper for) */
uint8_t MCP2515_ReadRegister(uint8_t address);
void    MCP2515_WriteRegister(uint8_t address, uint8_t value);
void    MCP2515_ModifyRegister(uint8_t address, uint8_t mask, uint8_t value);
uint8_t MCP2515_ReadStatus(void);

/* Send a frame via TXB0. Returns HAL_OK if successfully loaded and requested
 * for transmission (does not block waiting for bus arbitration/ACK). */
HAL_StatusTypeDef MCP2515_SendMessage(CAN_Frame *frame);

/* Returns 1 if a message is waiting in RXB0 or RXB1, else 0.
 * Call this from your INT pin's EXTI callback, or poll it. */
uint8_t MCP2515_CheckReceive(void);

/* Reads whichever RX buffer has data (checks RXB0 first, then RXB1),
 * clears the corresponding interrupt flag. Returns HAL_OK if a frame
 * was actually read, HAL_ERROR if nothing was pending. */
HAL_StatusTypeDef MCP2515_ReadMessage(CAN_Frame *frame);

/* Self-test using the MCP2515's internal Loopback mode — no second node
 * or CAN bus wiring required. Puts the chip in Loopback, sends a known
 * test frame, verifies it comes back byte-for-byte via the RX buffer,
 * then restores Normal mode regardless of outcome.
 * Returns HAL_OK if the frame round-tripped correctly, HAL_ERROR otherwise
 * (either nothing came back within the timeout, or the data didn't match —
 * both indicate an SPI/wiring/driver problem worth chasing before wiring
 * up the real bus). */
HAL_StatusTypeDef MCP2515_LoopbackSelfTest(void);

#endif /* MCP2515_H */
