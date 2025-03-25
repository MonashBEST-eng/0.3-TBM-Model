import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FormUploaderComponent } from './form-uploader.component';

describe('FormUploaderComponent', () => {
  let component: FormUploaderComponent;
  let fixture: ComponentFixture<FormUploaderComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FormUploaderComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(FormUploaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
