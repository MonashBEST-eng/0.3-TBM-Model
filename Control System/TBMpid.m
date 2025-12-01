% -----------------------------Monash BEST--------------------------------
% Project/Task Title: PID script for TBM
% -------------------------------------------------------------------------
% Description: Provide a brief overview of the project or assignment.
%
% Author/s: Phu Quach
% Date:  17/1/24
%
% -------------------------------------------------------------------------
% Comments and Additional Notes
% -------------------------------------------------------------------------
% Add any additional comments or notes here

clc; clear; close all;

% -------------------------------------------------------------------------
% Section 1: Initialization
% -------------------------------------------------------------------------
% Please ensure the code has useful and understandable annotations for 
% relevant/complicated lines of code
% Please ensure each section of code has a brief title

% Initialise gains for PID controller
kp = 1; % Proportional gain
ki = 0.1; % Integral gain
kd = 0.2; % Derivative gain

s = tf('s'); % Initialising s variable for transfer functions

% -------------------------------------------------------------------------
% Section 2: Main Code
% -------------------------------------------------------------------------
% Your main code goes here

% Insert Transfer function for the TBM
TBM_transfer = ...
    


% Example code:
%Calling generate_data to add both variables
[data1, data2] = generate_data(param1, param2); % Calling function generate_data
addition = data1 + data2; % Adding two variables

% -------------------------------------------------------------------------
% End of Script
% -------------------------------------------------------------------------