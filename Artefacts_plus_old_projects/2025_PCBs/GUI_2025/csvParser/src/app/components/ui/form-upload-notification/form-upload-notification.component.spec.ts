import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FormUploadNotificationComponent } from './form-upload-notification.component';

describe('FormUploadNotificationComponent', () => {
  let component: FormUploadNotificationComponent;
  let fixture: ComponentFixture<FormUploadNotificationComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FormUploadNotificationComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(FormUploadNotificationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
