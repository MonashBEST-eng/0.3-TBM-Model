import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-form-upload-notification',
  imports: [],
  templateUrl: './form-upload-notification.component.html',
  styleUrl: './form-upload-notification.component.scss'
})
export class FormUploadNotificationComponent {
    @Input({required : true}) file: File | null = null;
}
