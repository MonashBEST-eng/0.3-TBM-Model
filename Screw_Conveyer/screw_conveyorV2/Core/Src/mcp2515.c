/*
 * mcp2515.c
 *
 * MCP2515 CAN Controller Driver — STM32 HAL SPI
 * See mcp2515.h for wiring assumptions and bit-timing config.
 */

#include "mcp2515.h"
#include <string.h>

static SPI_HandleTypeDef *mcp_hspi;

#define SPI_TIMEOUT_MS  100

/* DIAGNOSTIC: tracks whether the most recent SPI transaction actually
 * completed, or failed/timed out. The driver previously never checked
 * HAL_SPI_TransmitReceive()'s return status at all - meaning a genuine
 * SPI-level failure (e.g. a timeout) would silently leave the zero-
 * initialized rx[] buffer untouched, and MCP2515_ReadRegister() would
 * return 0x00 looking exactly like "the chip responded with 0", when
 * actually no transaction completed at all. Call
 * MCP2515_GetLastSpiError() after a suspicious read to tell the two
 * cases apart. */
static volatile HAL_StatusTypeDef mcp2515_last_spi_status = HAL_OK;

HAL_StatusTypeDef MCP2515_GetLastSpiStatus(void)
{
    return mcp2515_last_spi_status;
}

/* ==========================================================================
 * LOW-LEVEL SPI HELPERS
 * ==========================================================================*/

static void MCP2515_SpiTransmit(uint8_t *tx, uint16_t len)
{
    mcp2515_last_spi_status = HAL_SPI_Transmit(mcp_hspi, tx, len, SPI_TIMEOUT_MS);
}

static void MCP2515_SpiTransmitReceive(uint8_t *tx, uint8_t *rx, uint16_t len)
{
    mcp2515_last_spi_status = HAL_SPI_TransmitReceive(mcp_hspi, tx, rx, len, SPI_TIMEOUT_MS);
}

uint8_t MCP2515_ReadRegister(uint8_t address)
{
    uint8_t tx[3] = { MCP2515_INSTR_READ, address, 0x00 };
    uint8_t rx[3] = { 0 };

    MCP2515_CS_LOW();
    MCP2515_SpiTransmitReceive(tx, rx, 3);
    MCP2515_CS_HIGH();

    return rx[2];
}

void MCP2515_WriteRegister(uint8_t address, uint8_t value)
{
    uint8_t tx[3] = { MCP2515_INSTR_WRITE, address, value };

    MCP2515_CS_LOW();
    MCP2515_SpiTransmit(tx, 3);
    MCP2515_CS_HIGH();
}

void MCP2515_ModifyRegister(uint8_t address, uint8_t mask, uint8_t value)
{
    uint8_t tx[4] = { MCP2515_INSTR_BIT_MODIFY, address, mask, value };

    MCP2515_CS_LOW();
    MCP2515_SpiTransmit(tx, 4);
    MCP2515_CS_HIGH();
}

uint8_t MCP2515_ReadStatus(void)
{
    uint8_t tx[2] = { MCP2515_INSTR_READ_STATUS, 0x00 };
    uint8_t rx[2] = { 0 };

    MCP2515_CS_LOW();
    MCP2515_SpiTransmitReceive(tx, rx, 2);
    MCP2515_CS_HIGH();

    return rx[1];
}

static void MCP2515_Reset(void)
{
    uint8_t tx = MCP2515_INSTR_RESET;

    MCP2515_CS_LOW();
    MCP2515_SpiTransmit(&tx, 1);
    MCP2515_CS_HIGH();

    HAL_Delay(10);   /* datasheet: allow oscillator startup time after reset */
}

static HAL_StatusTypeDef MCP2515_SetMode(uint8_t mode)
{
    uint32_t start = HAL_GetTick();

    MCP2515_ModifyRegister(MCP2515_CANCTRL, MCP2515_MODE_MASK, mode);

    /* Poll CANSTAT until the mode actually takes effect */
    while ((MCP2515_ReadRegister(MCP2515_CANSTAT) & MCP2515_MODE_MASK) != mode)
    {
        if ((HAL_GetTick() - start) > SPI_TIMEOUT_MS)
        {
            return HAL_ERROR;
        }
    }
    return HAL_OK;
}

/* ==========================================================================
 * INIT
 * ==========================================================================*/

HAL_StatusTypeDef MCP2515_Init(SPI_HandleTypeDef *hspi)
{
    mcp_hspi = hspi;

    MCP2515_CS_HIGH();   /* idle state */
    HAL_Delay(10);

    MCP2515_Reset();

    /* Must be in Configuration mode to write CNF1/2/3 and filters/masks */
    if (MCP2515_SetMode(MCP2515_MODE_CONFIG) != HAL_OK)
    {
        return HAL_ERROR;
    }

    /* Bit timing: 8 MHz oscillator, 500 kbps */
    MCP2515_WriteRegister(MCP2515_CNF1, MCP2515_CNF1_8MHZ_500KBPS);
    MCP2515_WriteRegister(MCP2515_CNF2, MCP2515_CNF2_8MHZ_500KBPS);
    MCP2515_WriteRegister(MCP2515_CNF3, MCP2515_CNF3_8MHZ_500KBPS);

    /* Accept-all filtering for now (no mask/filter narrowing) — every
     * device on the bus will receive every frame; you can tighten this
     * later once each STM's device ID is finalized. */
    MCP2515_WriteRegister(MCP2515_RXB0CTRL,
                           MCP2515_RXB0CTRL_RXM_ANY | MCP2515_RXB0CTRL_BUKT);
    MCP2515_WriteRegister(MCP2515_RXB1CTRL, MCP2515_RXB0CTRL_RXM_ANY);

    /* Enable receive interrupts for both buffers */
    MCP2515_WriteRegister(MCP2515_CANINTE,
                           MCP2515_CANINTF_RX0IF | MCP2515_CANINTF_RX1IF);

    /* Clear any stale interrupt flags */
    MCP2515_WriteRegister(MCP2515_CANINTF, 0x00);

    /* Leave Configuration mode -> Normal mode (actively transmits/receives,
     * participates in bus arbitration and ACK) */
    return MCP2515_SetMode(MCP2515_MODE_NORMAL);
}

/* ==========================================================================
 * TRANSMIT
 * ==========================================================================*/

HAL_StatusTypeDef MCP2515_SendMessage(CAN_Frame *frame)
{
    uint8_t buf[5 + 8];   /* SIDH,SIDL,EID8,EID0,DLC + up to 8 data bytes */
    uint8_t len = 0;

    if (frame->dlc > 8) return HAL_ERROR;

    if (frame->ext)
    {
        /* 29-bit extended ID split across SIDH/SIDL/EID8/EID0 per datasheet
         * Table 4-2. SIDL bit 3 (EXIDE) = 1 marks this as an extended frame. */
        uint32_t id = frame->id;
        buf[len++] = (uint8_t)(id >> 21);                          /* SIDH: ID28-21 */
        buf[len++] = (uint8_t)(((id >> 18) & 0x07) << 5)
                     | 0x08                                        /* EXIDE bit */
                     | (uint8_t)((id >> 16) & 0x03);                /* SIDL */
        buf[len++] = (uint8_t)(id >> 8);                            /* EID8 */
        buf[len++] = (uint8_t)(id);                                 /* EID0 */
    }
    else
    {
        uint32_t id = frame->id & 0x7FF;
        buf[len++] = (uint8_t)(id >> 3);        /* SIDH: ID10-3 */
        buf[len++] = (uint8_t)((id & 0x07) << 5); /* SIDL: ID2-0 in bits 7-5 */
        buf[len++] = 0x00;                       /* EID8 unused */
        buf[len++] = 0x00;                       /* EID0 unused */
    }

    buf[len++] = (frame->rtr ? 0x40 : 0x00) | (frame->dlc & 0x0F);

    for (uint8_t i = 0; i < frame->dlc; i++)
    {
        buf[len++] = frame->data[i];
    }

    /* Load TXB0 starting at SIDH (TXB0SIDH) in one burst write */
    uint8_t tx_header[2] = { MCP2515_INSTR_WRITE, MCP2515_TXB0SIDH };
    MCP2515_CS_LOW();
    MCP2515_SpiTransmit(tx_header, 2);
    MCP2515_SpiTransmit(buf, len);
    MCP2515_CS_HIGH();

    /* Request-to-send for TXB0 */
    uint8_t rts = MCP2515_INSTR_RTS | 0x01;
    MCP2515_CS_LOW();
    MCP2515_SpiTransmit(&rts, 1);
    MCP2515_CS_HIGH();

    return HAL_OK;
}

/* ==========================================================================
 * RECEIVE
 * ==========================================================================*/

uint8_t MCP2515_CheckReceive(void)
{
    uint8_t intf = MCP2515_ReadRegister(MCP2515_CANINTF);
    return (intf & (MCP2515_CANINTF_RX0IF | MCP2515_CANINTF_RX1IF)) != 0;
}

static HAL_StatusTypeDef MCP2515_ReadBuffer(uint8_t sidh_addr, uint8_t intf_clear_mask,
                                             CAN_Frame *frame)
{
    /* Fixed-size transfer: 2 bytes (instruction+address) + 5 bytes (SIDH,
     * SIDL, EID8, EID0, DLC) + 8 bytes (max data payload) = 15 total.
     * Real register data doesn't start appearing until 2 bytes AFTER the
     * instruction+address are clocked out - rx[0] and rx[1] are meaningless
     * filler while the MCP2515 is still processing the request. */
    uint8_t tx[2 + 5 + 8] = { 0 };
    uint8_t rx[2 + 5 + 8] = { 0 };

    tx[0] = MCP2515_INSTR_READ;
    tx[1] = sidh_addr;

    MCP2515_CS_LOW();
    MCP2515_SpiTransmitReceive(tx, rx, sizeof(tx));
    MCP2515_CS_HIGH();

    uint8_t sidh     = rx[2];
    uint8_t sidl     = rx[3];
    uint8_t eid8     = rx[4];
    uint8_t eid0     = rx[5];
    uint8_t dlc_byte = rx[6];
    uint8_t dlc      = dlc_byte & 0x0F;

    if (dlc > 8) dlc = 8;

    if (sidl & 0x08)   /* EXIDE set -> extended frame */
    {
        frame->ext = 1;
        frame->id  = ((uint32_t)sidh << 21)
                    | (((uint32_t)sidl >> 5) << 18)
                    | (((uint32_t)sidl & 0x03) << 16)
                    | ((uint32_t)eid8 << 8)
                    | (uint32_t)eid0;
    }
    else
    {
        frame->ext = 0;
        frame->id  = ((uint32_t)sidh << 3) | ((uint32_t)sidl >> 5);
    }

    frame->rtr = (dlc_byte & 0x40) ? 1 : 0;
    frame->dlc = dlc;
    for (uint8_t i = 0; i < dlc; i++)
    {
        frame->data[i] = rx[7 + i];
    }

    /* Clear the RX interrupt flag for the buffer we just read */
    MCP2515_ModifyRegister(MCP2515_CANINTF, intf_clear_mask, 0x00);

    return HAL_OK;
}

HAL_StatusTypeDef MCP2515_ReadMessage(CAN_Frame *frame)
{
    uint8_t intf = MCP2515_ReadRegister(MCP2515_CANINTF);

    if (intf & MCP2515_CANINTF_RX0IF)
    {
        return MCP2515_ReadBuffer(MCP2515_RXB0SIDH, MCP2515_CANINTF_RX0IF, frame);
    }
    else if (intf & MCP2515_CANINTF_RX1IF)
    {
        return MCP2515_ReadBuffer(MCP2515_RXB1SIDH, MCP2515_CANINTF_RX1IF, frame);
    }

    return HAL_ERROR;   /* nothing pending */
}

/* ==========================================================================
 * LOOPBACK SELF-TEST
 * ==========================================================================*/

HAL_StatusTypeDef MCP2515_LoopbackSelfTest(void)
{
    HAL_StatusTypeDef result;

    /* Enter Loopback mode: frames sent via TXB0 are routed straight to an
     * RX buffer internally — no bus traffic, no second node required. */
    if (MCP2515_SetMode(MCP2515_MODE_LOOPBACK) != HAL_OK)
    {
        MCP2515_SetMode(MCP2515_MODE_NORMAL);
        return HAL_ERROR;   /* couldn't even switch modes — SPI link itself is broken */
    }

    /* Clear any stale interrupt flags before the test frame goes out */
    MCP2515_WriteRegister(MCP2515_CANINTF, 0x00);

    CAN_Frame txFrame = { 0 };
    txFrame.id  = 0x7AA;
    txFrame.ext = 0;
    txFrame.rtr = 0;
    txFrame.dlc = 4;
    txFrame.data[0] = 0xCA;
    txFrame.data[1] = 0xFE;
    txFrame.data[2] = 0xBE;
    txFrame.data[3] = 0xEF;

    MCP2515_SendMessage(&txFrame);

    /* Poll for the looped-back frame, with a short timeout */
    uint32_t start = HAL_GetTick();
    while (!MCP2515_CheckReceive())
    {
        if ((HAL_GetTick() - start) > 200)
        {
            MCP2515_SetMode(MCP2515_MODE_NORMAL);
            return HAL_ERROR;   /* nothing came back within timeout */
        }
    }

    CAN_Frame rxFrame = { 0 };
    MCP2515_ReadMessage(&rxFrame);

    if (rxFrame.id  == txFrame.id  &&
        rxFrame.dlc == txFrame.dlc &&
        memcmp(rxFrame.data, txFrame.data, txFrame.dlc) == 0)
    {
        result = HAL_OK;
    }
    else
    {
        result = HAL_ERROR;   /* something came back, but corrupted/wrong */
    }

    /* Always restore Normal mode afterward so the chip is ready for real
     * bus operation regardless of test outcome. */
    MCP2515_SetMode(MCP2515_MODE_NORMAL);

    return result;
}
