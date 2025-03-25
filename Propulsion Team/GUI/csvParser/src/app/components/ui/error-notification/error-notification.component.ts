import { NgStyle } from '@angular/common';
import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-error-notification',
  imports: [NgStyle],
  templateUrl: './error-notification.component.html',
  styleUrl: './error-notification.component.scss'
})
export class ErrorNotificationComponent {
    @Input({required : true}) errorMessage: string = '';
    @Input({required : true}) show: boolean = false;
    @Input({required : true}) bgColour: string = '';
    @Input({required : true}) textColour: string = '';
    @Input({required : true}) borderColour: string = '';
}