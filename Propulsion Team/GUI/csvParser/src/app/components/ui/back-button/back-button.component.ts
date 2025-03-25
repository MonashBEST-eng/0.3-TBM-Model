import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { faSquareCaretLeft, faSquareCaretRight, faArrowLeft } from '@fortawesome/free-solid-svg-icons'; 
import { FileParserService } from '../../../services/file-parser/file-parser.service';

@Component({
  selector: 'app-back-button',
  imports: [FontAwesomeModule, RouterLink],
  templateUrl: './back-button.component.html',
  styleUrl: './back-button.component.scss'
})
export class BackButtonComponent {
    faArrowLeft = faArrowLeft;
    constructor( private fileParser: FileParserService){}

    // Reload fileParser memory
    reload(){
        this.fileParser.reload();
    }

}
