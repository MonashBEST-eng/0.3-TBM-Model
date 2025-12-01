// Arduino Mega code for controlling and reading hall sensors

#include <Encoder.h>

// Define the pins connected to the Hall sensors for each actuator, using interrupt pins
const int HALL_A_PINS[3] = {2, 19, 17};  // Signal A for actuators 1, 2, 3 (Interrupt pins 2, 3, 18)
const int HALL_B_PINS[3] = {3, 18, 16}; // Signal B for actuators 1, 2, 3 (Interrupt pins 21, 20, 19)

const float DISTANCE_PER_PULSE[3] = {0.0273, 0.026, 0.027};  // Distance per pulse for actuators

// Define the motor driver pins for each actuator
const int ENA = 5;
const int IN1 = 6;
const int IN2 = 7;
const int ENB = 8;
const int IN3 = 9;
const int IN4 = 10;
const int ENC = 11;
const int IN5 = 12;
const int IN6 = 13;

// Motor pins and direction pins
const int motor_pins[3] = {ENA, ENB, ENC};
const int motor_dir_pins[3] = {IN1, IN3, IN5};
const int motor_dir_pins2[3] = {IN2, IN4, IN6};

// Create encoder objects for each actuator
Encoder encoders[3] = {
    Encoder(HALL_A_PINS[0], HALL_B_PINS[0]),
    Encoder(HALL_A_PINS[1], HALL_B_PINS[1]),
    Encoder(HALL_A_PINS[2], HALL_B_PINS[2])
};

// PID gains for each actuator
float Kp[3] = {1.0, 1.0, 1.0};
float Ki[3] = {0.1, 0.1, 0.1};
float Kd[3] = {0.01, 0.01, 0.01};

// Error and integral terms for each actuator
float errors[3] = {0.0, 0.0, 0.0};
float integral_errors[3] = {0.0, 0.0, 0.0};
float previous_errors[3] = {0.0, 0.0, 0.0};

// Tolerance for error
float tolerance = 0.1 //placeholder

// Variables to store pulses, positions, velocities
volatile long pulses[3] = {0, 0, 0};
float positions[3] = {0.0, 0.0, 0.0};
float velocities[3] = {0.0, 0.0, 0.0};

// Time tracking for velocity calculation
unsigned long lastTimes[3] = {0, 0, 0};
volatile long previousPulses[3] = {0, 0, 0};

void setup() {
  Serial.begin(9600);  // Initialize serial communication
  Serial.println("System Initialized.");
  Serial.println("Enter target position (in mm) via Serial Monitor:");

  // Initialize encoder positions to 0
  for (int i = 0; i < 3; ++i) {
    encoders[i].write(0);
    lastTimes[i] = millis();  // Record the initial time
  }

  // Set motor driver pins as outputs
  pinMode(ENA, OUTPUT); pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT); pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(ENC, OUTPUT); pinMode(IN5, OUTPUT); pinMode(IN6, OUTPUT);

  // Attach interrupts for the Hall sensors
  attachInterrupt(digitalPinToInterrupt(HALL_A_PINS[0]), handleInterrupt1, CHANGE);
  attachInterrupt(digitalPinToInterrupt(HALL_A_PINS[1]), handleInterrupt2, CHANGE);
  attachInterrupt(digitalPinToInterrupt(HALL_A_PINS[2]), handleInterrupt3, CHANGE);
}

void loop() {
  // Check if the user has entered a target position via Serial Monitor
  if (Serial.available() > 0) {
    Serial.println("Enter a target position (in mm) (max 150):");  // Prompt user input
    String inputString = Serial.readStringUntil('\n');    // Read user input
    float target_position = inputString.toFloat();        // Convert input to float

    // Validate input and take action
    if (isnan(target_position) || target_position > 150) {
      Serial.println("Invalid input!");
    } else {
      float average_position = (positions[0] + positions[1] + positions[2]) / 3;
      if (average_position < target_position) {
        extend(255, target_position);  // Extend actuators towards target
      } else if (average_position > target_position) {
        retract(255, target_position);  // Retract actuators towards target
      }
    }
  }
}

// Interrupt service routines for each actuator
void handleInterrupt1() { pulses[0] = encoders[0].read(); }
void handleInterrupt2() { pulses[1] = encoders[1].read(); }
void handleInterrupt3() { pulses[2] = encoders[2].read(); }

// Function to update position and velocity for an actuator
void updateActuator(int index) {

  // Ensure the position stays non-negative
  if (positions[index] < 0) {
    positions[index] = 0;
  }

  unsigned long currentTime = millis();
  if (currentTime - lastTimes[index] >= 0) {  // Calculate velocity every 0 ms
    positions[index] = pulses[index] * DISTANCE_PER_PULSE[index];  // Calculate position in mm
    long positionChange = pulses[index] - previousPulses[index];
    velocities[index] = abs((float)(positionChange * DISTANCE_PER_PULSE[index]) /
                            ((currentTime - lastTimes[index]) / 1000.0));  // mm/s

    previousPulses[index] = pulses[index];  // Update previous pulse count
    lastTimes[index] = currentTime;         // Update last time
  }
  //printAllActuatorInfo();  // Print actuator info in one line
}

// Function to stop an actuator
void stopActuator(int actuator_id) {
  switch (actuator_id) {
    case 1: digitalWrite(ENA, LOW); break;
    case 2: digitalWrite(ENB, LOW); break;
    case 3: digitalWrite(ENC, LOW); break;
  }
}

// Function to extend the actuator with speed control
void extend(int speed, float target_position) {
  Serial.print("Extending towards "); Serial.print(target_position); Serial.println(" mm");
  
  // Use a flag to track if any actuator is still moving
  bool isMoving = true;

  while (isMoving) {
    isMoving = false; // Assume no actuators are moving
    Serial.print("Positions: ");
    Serial.print(positions[0]);
    Serial.print(", ");
    Serial.print(positions[1]);
    Serial.print(", ");
    Serial.print(positions[2]);
    Serial.println();  // Print a new line at the end
    
    updateAllActuators();  // Update positions during extension

    for (int i = 0; i < 3; ++i) {
      errors[i] = target_position - positions[i];
      integral_errors[i] += errors[i];
      float derivative_error = errors[i] - previous_errors[i];
      float pid_output = Kp[i] * errors[i] + Ki[i] * integral_errors[i] + Kd[i] * derivative_error;

      // Limit the PID output to a reasonable range (e.g., 0-255)
      pid_output = constrain(pid_output, 0, 255);

      // Set motor speed and direction based on PID output
      if (errors[i] > 0) {
        // Forward motion
        analogWrite(motor_pins[i], pid_output);
        digitalWrite(motor_dir_pins[i], HIGH);
        digitalWrite(motor_dir_pins2[i], LOW);
      } else {
        // Reverse motion (if needed for overshoot correction)
        analogWrite(motor_pins[i], pid_output);
        digitalWrite(motor_dir_pins[i], LOW);
        digitalWrite(motor_dir_pins2[i], HIGH);
      }
    // Check if the actuator has reached the target position and stop if it has
      if (abs(errors[i]) < tolerance) {
        stopActuator(i + 1);
        isMoving = false;
      } else {
        isMoving = true;
      }

      previous_errors[i] = errors[i];
    }

    // Check each actuator's position
    for (int i = 0; i < 3; ++i) {
      if (positions[i] >= target_position) {
        stopActuator(i + 1); // Stop this actuator
        Serial.print("Actuator "); Serial.print(i + 1); Serial.println(" reached target position.");
      } else {
        isMoving = true; // If any actuator hasn't reached the target, keep moving
      }
    }
  }

  Serial.println("Extension complete.");
  stopAllMotors();  // Stop motors when done
}

// Function to retract the actuator with speed control
void retract(int speed, float target_position) {
  Serial.print("Retracting towards "); Serial.print(target_position); Serial.println(" mm");
  
  // Use a flag to track if any actuator is still moving
  bool isMoving = true;

  while (isMoving) {
    isMoving = false; // Assume no actuators are moving
    Serial.print("Positions: ");
    Serial.print(positions[0]);
    Serial.print(", ");
    Serial.print(positions[1]);
    Serial.print(", ");
    Serial.print(positions[2]);
    Serial.println();  // Print a new line at the end
    
    updateAllActuators();  // Update positions during retraction

    for (int i = 0; i < 3; ++i) {
      errors[i] = target_position - positions[i];
      integral_errors[i] += errors[i];
      float derivative_error = errors[i] - previous_errors[i];
      float pid_output = Kp[i] * errors[i] + Ki[i] * integral_errors[i] + Kd[i] * derivative_error;

      // Limit the PID output to a reasonable range (e.g., 0-255)
      pid_output = constrain(pid_output, 0, 255);

      // Set motor speed and direction based on PID output
      if (errors[i]< 0) { // Less than because we are retracting
        // Forward motion
        analogWrite(motor_pins[i], pid_output);
        digitalWrite(motor_dir_pins[i], LOW);
        digitalWrite(motor_dir_pins2[i], HIGH);
      } else {
        // Reverse motion (if needed for overshoot correction)
        analogWrite(motor_pins[i], pid_output);
        digitalWrite(motor_dir_pins[i], HIGH);
        digitalWrite(motor_dir_pins2[i], LOW);
      }
        // Check if the actuator has reached the target position and stop if it has
      if (abs(errors[i]) < tolerance) {
        stopActuator(i + 1);
        isMoving = false;
      } else {
        isMoving = true;
      }

      previous_errors[i] = errors[i];
    }

    // Check each actuator's position
    for (int i = 0; i < 3; ++i) {
      if (positions[i] <= target_position) {
        stopActuator(i + 1); // Stop this actuator
        Serial.print("Actuator "); Serial.print(i + 1); Serial.println(" reached target position.");
      } else {
        isMoving = true; // If any actuator hasn't reached the target, keep moving
      }
    }
  }
  Serial.println("Retraction complete.");
  stopAllMotors();  // Stop motors when done
}

// Function to stop all motors
void stopAllMotors() {
  for (int i = 1; i <= 3; ++i) {
    stopActuator(i);
  }
}

// Function to update all actuator positions
void updateAllActuators() {
  for (int i = 0; i < 3; ++i) {
    updateActuator(i);
  }
}

// Function to print all actuators' information in one line
void printAllActuatorInfo() {
  Serial.print("1,");
  Serial.print(positions[0]);
  Serial.print(", ");
  Serial.print(velocities[0]);
  Serial.print(" mm/s, 2, ");
  Serial.print(positions[1]);
  Serial.print(", ");
  Serial.print(velocities[1]);
  Serial.print(" mm/s, 3, ");
  Serial.print(positions[2]);
  Serial.print(", ");
  Serial.print(velocities[2]);
  Serial.println(" mm/s");
}
