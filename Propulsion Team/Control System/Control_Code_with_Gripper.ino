#include <Arduino.h>

// Define the motor driver pins for each actuator
// Front-right actuator
const int ena = 49;
const int int1 = 43;
const int int2 = 42;
// Back actuator
const int enb = 5;
const int int3 = 6;
const int int4 = 7;
// Front-left actuator
const int enc = 31;
const int int5 = 32;
const int int6 = 33;
// Front actuator
const int end = 29;
const int int7 = 30;
const int int8 = 28;
// Gripper 1 actuator
const int ene = 22;
const int int9 = 23;
const int int10 = 24;
// Gripper 2 actuator
const int enf = 25;
const int int11 = 26;
const int int12 = 27;
// Rear Gripper 3 actuator
const int eng = 39;
const int int13 = 38;
const int int14 = 40;
// Rear Gripper 4 actuator
const int enh = 11;
const int int15 = 12;
const int int16 = 13;

float cur_distance[4] = {0.0, 0.0, 0.0, 0.0};
float cur_gripper[4] = {0.0, 0.0, 0.0, 0.0};

int velocity_prop = 4; // 4 mm/s
int velocity_gripper = 18; // 20 mm/s


void setup() {
  pinMode(int1, OUTPUT);
  pinMode(int2, OUTPUT);
  pinMode(ena, OUTPUT);
  pinMode(int3, OUTPUT);
  pinMode(int4, OUTPUT);
  pinMode(enb, OUTPUT);
  pinMode(int5, OUTPUT);
  pinMode(int6, OUTPUT);
  pinMode(enc, OUTPUT);
  pinMode(int7, OUTPUT);
  pinMode(int8, OUTPUT);
  pinMode(end, OUTPUT);
  pinMode(int9, OUTPUT);
  pinMode(int10, OUTPUT);
  pinMode(ene, OUTPUT);
  pinMode(int11, OUTPUT);
  pinMode(int12, OUTPUT);
  pinMode(enf, OUTPUT);
  pinMode(int13, OUTPUT);
  pinMode(int14, OUTPUT);
  pinMode(eng, OUTPUT);
  pinMode(int15, OUTPUT);
  pinMode(int16, OUTPUT);
  pinMode(enh, OUTPUT);

  Serial.begin(9600);

  // Wait for user input to begin
  Serial.println("");
  Serial.println("System is ready. Enter 'BEGIN' to start:");
  while (true) {
    if (Serial.available()) {
      String input = Serial.readStringUntil('\n');
      input.trim(); // Remove any whitespace or newline characters
      if (input.equalsIgnoreCase("BEGIN")) {
        Serial.println("Starting actuator control...");
        break;
      } else {
        Serial.println("Invalid input. Please enter 'BEGIN' to start:");
      }
    }
  }
}

void loop() {
    // Declare a vector of vectors to store lengths
    int num_sequence = 3;
    int num_motors = 4;
    int desired_lengths[num_sequence][num_motors] = {{100,100,100,100}, {0, 0, 0, 0}, {0,0,0,0}};
    int desired_gripperLengths[num_sequence][num_motors] = {{0, 0, 50, 50}, {50, 50, 0, 0},{0,0,0,0}};
    
    // Loop through each sub-vector (representing a joint)
    for (int i = 0; i < 3; i++) {
        if (i == 0){
          Serial.println("Delaying for 15 seconds.");
          delay(1000);
        }
        else if (i == 1){
          Serial.println("Delaying for 10 seconds.");
          delay(1000);
        }
        unsigned long startTimes[4];
        float moveTimes_Gripper[4];
        float moveTimes[4];
        bool motorStopped[4] = {false, false, false, false}; // Array to track stopped motors
        bool gripperStopped[4] = {false, false, false, false}; // Array to track stopped grippers
        
        // Calculate movement times and store target lengths
        for (int j = 0; j < 4; j++) {
            Serial.print("Current Gripper ");
            Serial.print(j+1);
            Serial.print(" :");
            Serial.println(cur_gripper[j]);
            Serial.print("Current Actuator ");
            Serial.print(j+1);
            Serial.print(" :");
            Serial.println(cur_distance[j]);
            moveTimes[j] = calTime_Dist(cur_distance[j], desired_lengths[i][j], velocity_prop) * 1000; // Calculate time in milliseconds
            moveTimes_Gripper[j] = calTime_Dist(cur_gripper[j], desired_gripperLengths[i][j], velocity_gripper) * 1000; // Calculate time in milliseconds
            startTimes[j] = millis(); // Record the start time for each motor

            if (desired_lengths[i][j]> cur_distance[j]) {
                Serial.print("Extending actuator: ");
                Serial.println(j + 1);
                extend(j);
            } else if (desired_lengths[i][j] < cur_distance[j]) {
                Serial.print("Retracting actuator: ");
                Serial.println(j + 1);
                retract(j);
            } else {
                motorStopped[j] = true;
            }

            // Start gripper movement if required
            if (desired_gripperLengths[i][j] > cur_gripper[j] && !gripperStopped[j]) {
                Serial.print("Extending Gripper: ");
                Serial.println(j + 1);
                Gripper_extend(j);
            } else if (desired_gripperLengths[i][j] < cur_gripper[j] && !gripperStopped[j]) {
                Serial.print("Retracting Gripper: ");
                Serial.println(j + 1);
                Gripper_retract(j);
            } else {
                gripperStopped[j] = true;
            }
        }

        // Monitor both actuator and gripper movements and stop them individually
        bool allMotorsStopped = false;
        bool allGrippersStopped = false;

        while (!allMotorsStopped || !allGrippersStopped) {
            allMotorsStopped = true;
            allGrippersStopped = true;

            // Monitor actuator movements
            for (int j = 0; j < 4; j++) {
                if (!motorStopped[j]) {
                    unsigned long elapsedTime = millis() - startTimes[j];
                    if (elapsedTime >= moveTimes[j]) {
                        stopMotor(j);
                        motorStopped[j] = true;
                        cur_distance[j] = desired_lengths[i][j]; // Update current gripper length
                    } else {
                        allMotorsStopped = false;
                    }
                }
            }

            // Monitor gripper movements
            for (int j = 0; j < 4; j++) {
                if (!gripperStopped[j]) {
                    unsigned long elapsedTimeGripper = millis() - startTimes[j];
                    if (elapsedTimeGripper >= moveTimes_Gripper[j]) {
                        stopMotor_gripper(j);
                        gripperStopped[j] = true;
                        cur_gripper[j] = desired_gripperLengths[i][j]; // Update current gripper length

                    } else {
                        allGrippersStopped = false;
                    }
                }
              }
            }
        
        // Reset to the first sequence if needed
        if (i >= 3) {
            i = 0; // Reset to the first sequence
            Serial.println("Restarting sequence.");
        }
    }
}

void extend(int jointIndex) {
  int directionPins[] = {int1, int3, int5, int7};
  int directionPinsB[] = {int2, int4, int6, int8};
  int enablePins[] = {ena, enb, enc, end};

  digitalWrite(directionPins[jointIndex], HIGH);
  digitalWrite(directionPinsB[jointIndex], LOW);
  digitalWrite(enablePins[jointIndex], HIGH);
}

void retract(int jointIndex) {
  int directionPinsA[] = {int1, int3, int5, int7};
  int directionPins[] = {int2, int4, int6, int8};
  int enablePins[] = {ena, enb, enc, end};

  digitalWrite(directionPinsA[jointIndex], LOW);
  digitalWrite(directionPins[jointIndex], HIGH);
  digitalWrite(enablePins[jointIndex], HIGH);
}

void Gripper_extend(int jointIndex) {
  int directionPinsA[] = {int9, int11, int13, int15};
  int directionPins[] = {int10, int12, int14, int16};
  int enablePins[] = {ene, enf, eng, enh};

  digitalWrite(directionPinsA[jointIndex], HIGH);
  digitalWrite(directionPins[jointIndex], LOW);
  digitalWrite(enablePins[jointIndex], HIGH);
}

void Gripper_retract(int jointIndex) {
  int directionPinsA[] = {int9, int11, int13, int15};
  int directionPins[] = {int10, int12, int14, int16};
  int enablePins[] = {ene, enf, eng, enh};

  digitalWrite(directionPinsA[jointIndex], LOW);
  digitalWrite(directionPins[jointIndex], HIGH);
  digitalWrite(enablePins[jointIndex], HIGH);
}

void stopMotor(int jointIndex) {

  int enablePins[] = {ena, enb, enc, end};
 
  Serial.print("Stopping joint ");

  Serial.println(jointIndex + 1);

  digitalWrite(enablePins[jointIndex], LOW);

}

void stopMotor_gripper(int jointIndex) {

  int enablePins[] = {ene, enf, eng, enh};
 
  Serial.print("Stopping Gripper ");

  Serial.println(jointIndex + 1);

  digitalWrite(enablePins[jointIndex], LOW);

}

float calTime_Dist(float current_distance, int targetLength, int velocity) {

  if (velocity == velocity_prop){
    float time = (current_distance - targetLength) / velocity;
    if (time < 0){
      time = time * -1;
    }
    Serial.print("Target Length Prop: ");
    Serial.println(targetLength);
    Serial.print("Calculated time for joint: ");

    Serial.print(time);

    Serial.println(" seconds");

    return time;
  }
  else {
    float time = (current_distance - targetLength) / velocity;
    if (time < 0){
      time = time * -1;
    }
    Serial.print("Target Length Gripper: ");
    Serial.println(targetLength);
    Serial.print("Calculated time for gripper: ");
    Serial.print(time);

    Serial.println(" seconds");

    return time;
  }

}



