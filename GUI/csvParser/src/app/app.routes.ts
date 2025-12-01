import { Routes } from '@angular/router';
import { FormUploaderComponent } from './components/web-pages/form-uploader/form-uploader.component';
import { OutputGuiComponent } from './components/web-pages/output-gui/output-gui.component';
import { InvalidComponent } from './components/web-pages/invalid/invalid.component';

export const routes: Routes = [
    { path : '', component : FormUploaderComponent },
    { path : 'results', component : OutputGuiComponent },

    // Fall back
    {path : 'invalid', component : InvalidComponent},
    { path: '**', component : InvalidComponent},
];
