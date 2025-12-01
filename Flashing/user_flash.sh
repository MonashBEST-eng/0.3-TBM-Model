#!/bin/bash

# STM32 Flash Automation Script with Terminal UI
FLASH_ADDR="0x08000000"
TEMP_BIN="firmware.bin"
SERIAL_DEVICE="/dev/ttyACM0"
BAUD_RATE="115200"

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to display header
show_header() {
    clear
    echo -e "${BLUE}"
    echo "========================================"
    echo "      STM32 Flasher - Terminal UI       "
    echo "========================================"
    echo -e "${NC}"
}

# Function to display menu
show_menu() {
    echo -e "\n${YELLOW}Main Menu:${NC}"
    echo "1) Flash latest .elf file"
    echo "2) Select .elf file manually"
    echo "3) Check ST-Link connection"
    echo "4) Monitor serial output"
    echo "5) Exit"
    echo -n -e "${GREEN}Select an option [1-5]: ${NC}"
}

# Function to flash ELF file
flash_elf() {
    local elf_file="$1"
    
    echo -e "\n${YELLOW}Converting $elf_file to $TEMP_BIN...${NC}"
    if ! arm-none-eabi-objcopy -O binary "$elf_file" "$TEMP_BIN"; then
        echo -e "${RED}Conversion failed!${NC}"
        return 1
    fi

    echo -e "${YELLOW}Flashing to $FLASH_ADDR...${NC}"
    if ! st-flash --reset write "$TEMP_BIN" "$FLASH_ADDR"; then
        echo -e "${RED}Flashing failed!${NC}"
        return 1
    fi

    rm -f "$TEMP_BIN"
    echo -e "${GREEN}Flashing successful! Device has been reset.${NC}"
    return 0
}

detect_terminal() {
    if command -v konsole &> /dev/null; then
        echo "konsole -e "
    elif command -v xfce4-terminal &> /dev/null; then
        echo "xfce4-terminal -x "
    elif command -v xterm &> /dev/null; then
        echo "xterm -e "
    else
        echo -e "${RED}Debug: No terminal found (checked konsole, xfce4-terminal, xterm)${NC}" >&2
        echo ""
    fi
}

# Function to detect serial monitor tools
detect_serial_tool() {
    if command -v minicom &> /dev/null; then
        echo "minicom -D $SERIAL_DEVICE -b $BAUD_RATE"
    elif command -v screen &> /dev/null; then
        echo "screen $SERIAL_DEVICE $BAUD_RATE"
    else
        echo ""
    fi
}

# Function to monitor serial in external terminal
monitor_serial() {
    if [ ! -c "$SERIAL_DEVICE" ]; then
        echo -e "${RED}Serial device $SERIAL_DEVICE not found!${NC}"
        return
    fi
    
    local terminal=$(detect_terminal)
    local serial_tool=$(detect_serial_tool)
    
    if [ -z "$terminal" ]; then
        echo -e "${RED}No terminal emulator found!${NC}"
        echo "Please install one of: xterm, gnome-terminal, konsole, xfce4-terminal"
        return
    fi
    
    if [ -z "$serial_tool" ]; then
        echo -e "${RED}No serial monitor tool found!${NC}"
        echo "Please install one of: minicom, screen"
        return
    fi

    # echo -e "\n${YELLOW}Command to execute: $terminal $serial_tool${NC}"
    # if ! eval "$terminal $serial_tool"; then
    #     echo -e "${RED}Failed to open terminal!${NC}"
    # fi
    
    echo -e "\n${YELLOW}Opening serial monitor in external terminal...${NC}"
    eval "$terminal $serial_tool"
}

# Main function
main() {
    while true; do
        show_header
        show_menu
        
        read -r choice
        case $choice in
            1)
                elf_file=$(ls -t *.elf | head -1)
                if [ ! -f "$elf_file" ]; then
                    echo -e "${RED}No .elf files found in current directory!${NC}"
                    sleep 2
                    continue
                fi
                flash_elf "$elf_file"
                read -rp "Press any key to continue..."
                ;;
            2)
                elf_files=()
                while IFS= read -r -d $'\0' file; do
                    elf_files+=("$file")
                done < <(find . -maxdepth 1 -name "*.elf" -print0)
                
                if [ ${#elf_files[@]} -eq 0 ]; then
                    echo -e "${RED}No .elf files found in current directory!${NC}"
                    sleep 2
                    continue
                fi
                
                echo -e "\n${YELLOW}Available .elf files:${NC}"
                for i in "${!elf_files[@]}"; do
                    echo "$((i+1))) ${elf_files[$i]}"
                done
                
                echo -n -e "${GREEN}Select file [1-${#elf_files[@]}]: ${NC}"
                read -r file_choice
                
                if [[ "$file_choice" =~ ^[0-9]+$ ]] && [ "$file_choice" -ge 1 ] && [ "$file_choice" -le ${#elf_files[@]} ]; then
                    flash_elf "${elf_files[$((file_choice-1))]}"
                else
                    echo -e "${RED}Invalid selection!${NC}"
                fi
                read -rp "Press any key to continue..."
                ;;
            3)
                echo -e "\n${YELLOW}Checking ST-Link connection...${NC}"
                if st-info --probe >/dev/null 2>&1; then
                    echo -e "${GREEN}ST-Link detected!${NC}"
                    st-info --probe
                else
                    echo -e "${RED}ST-Link NOT detected!${NC}"
                    echo "Please check:"
                    echo "1. ST-Link is connected via USB"
                    echo "2. SWD pins are properly connected (SWDIO, SWCLK, GND)"
                    echo "3. You have proper permissions (try: sudo usermod -aG plugdev $USER)"
                fi
                read -rp "Press any key to continue..."
                ;;
            4)
                monitor_serial
                read -rp "Press any key to continue..."
                ;;
            5)
                echo -e "\n${BLUE}Exiting...${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option!${NC}"
                sleep 1
                ;;
        esac
    done
}

# Check dependencies
check_dependencies() {
    local missing=()
    local serial_tools_missing=()
    
    # Check for flashing tools
    if ! command -v arm-none-eabi-objcopy &> /dev/null; then
        missing+=("gcc-arm-none-eabi")
    fi
    
    if ! command -v st-flash &> /dev/null; then
        missing+=("stlink-tools")
    fi
    
    # Check for serial monitoring tools
    if ! command -v xterm &> /dev/null && ! command -v konsole &> /dev/null && ! command -v xfce4-terminal &> /dev/null; then
        serial_tools_missing+=("xterm")
    fi
    
    if ! command -v screen &> /dev/null && ! command -v minicom &> /dev/null; then
        serial_tools_missing+=("screen" "minicom")
    fi
    
    # Install missing dependencies if on Debian/Ubuntu
    if [ ${#missing[@]} -gt 0 ] || [ ${#serial_tools_missing[@]} -gt 0 ]; then
        echo -e "${RED}Missing dependencies:${NC}"
        [ ${#missing[@]} -gt 0 ] && echo " - Flashing tools: ${missing[*]}"
        [ ${#serial_tools_missing[@]} -gt 0 ] && echo " - Serial tools: ${serial_tools_missing[*]}"
        
        read -rp "Install now? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if [[ -f /etc/debian_version ]]; then
                echo -e "${YELLOW}Updating package lists and installing dependencies...${NC}"
                sudo apt update && sudo apt install -y "${missing[@]}" "${serial_tools_missing[@]}" || {
                    echo -e "${RED}Failed to install dependencies!${NC}"
                    exit 1
                }
                echo -e "${GREEN}Dependencies installed successfully!${NC}"
            else
                echo -e "${RED}Automatic installation only supported on Debian/Ubuntu${NC}"
                echo "Please install manually:"
                [ ${#missing[@]} -gt 0 ] && echo " - ${missing[*]}"
                [ ${#serial_tools_missing[@]} -gt 0 ] && echo " - ${serial_tools_missing[*]}"
                exit 1
            fi
        else
            exit 1
        fi
    fi
}

# Start the script
check_dependencies
main 