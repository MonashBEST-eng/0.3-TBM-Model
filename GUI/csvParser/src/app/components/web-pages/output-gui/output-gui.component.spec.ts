import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OutputGuiComponent } from './output-gui.component';

describe('OutputGuiComponent', () => {
  let component: OutputGuiComponent;
  let fixture: ComponentFixture<OutputGuiComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [OutputGuiComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(OutputGuiComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
