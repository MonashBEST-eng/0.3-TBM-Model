import { Component, HostListener, Output, ViewChild, EventEmitter, OnInit} from '@angular/core';
import { faArrowUpFromBracket } from '@fortawesome/free-solid-svg-icons'; 
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { FormUploadNotificationComponent } from '../../ui/form-upload-notification/form-upload-notification.component';
import { FileParserService } from '../../../services/file-parser/file-parser.service';
import { Router} from '@angular/router';
import { ErrorNotificationComponent } from '../../ui/error-notification/error-notification.component';

@Component({
  selector: 'app-form-uploader',
  imports: [FontAwesomeModule, FormUploadNotificationComponent, ErrorNotificationComponent],
  templateUrl: './form-uploader.component.html',
  styleUrl: './form-uploader.component.scss'
})
export class FormUploaderComponent {

    faUploadIcon = faArrowUpFromBracket
    files: FileList | null = null;
    all_files: File[] = [];
    fileHoverEffect = ["ring", "ring-blue-500", "ring-offset-2"];
    errorMessage: string = '';
    errorShow: boolean = false;

    @ViewChild('formUploader') formUploader: any;
    @ViewChild('fileInput') fileInput: any;

    constructor(private fileParser: FileParserService, private router : Router) {}

    // Get files from input element
    onFileChange( event: Event ) {
        let files: FileList | null = event.target ? (event.target as HTMLInputElement).files : null;
        if (!files){
            console.log('No files selected');
            this.showErrorMessage('No files selected', 7000);
            return;
        }
            
        this.processFiles(files);
    }

    // Process files and check if files are CSV
    processFiles ( files : FileList ) {
        Array.from(files).forEach(file => {
            // Check if file entered is a csv file
            if (file.type === 'text/csv'){
                this.all_files.push(file);
                console.log(file);
                console.log('CSV file detected')
            }
            else {
                console.log('Not a CSV file');
                this.showErrorMessage('Invalid file type. Please upload a CSV file', 7000);
            }
        });
    }

    // Upload files logic
    // Called after button is clicked
    uploadFiles (){
        this.fileParser.uploadFiles(this.all_files).subscribe({
            complete: () => {
                console.log('Completed');
            },
            next: () => {
                this.router.navigate(['results']);
            },
            error: (err) => {
                console.log(err);
                this.all_files = [];
                this.showErrorMessage('Invalid csv format. CSV must be of the form (number number)', 7000);
                this.router.navigate(['/']);
            }}
        );
    }

    // Error message timing function
    showErrorMessage(message: string, duration: number = 5000){
        this.errorMessage = message;
        this.errorShow = true;
        setTimeout(() => {
            this.errorShow = false;
        }, duration);
    }

    // DRAG OVER EFFECTS
    @HostListener('dragover', ['$event']) onDragOver(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        for (let i of this.fileHoverEffect){
            this.formUploader.nativeElement.classList.add(i);
        }

        console.log('drag over');
    }

    // DRAG LEAVE EFFECTS
    @HostListener('dragleave', ['$event']) onDragLeave(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        for (let i of this.fileHoverEffect){
            this.formUploader.nativeElement.classList.remove(i);
        }

        console.log('drag leave');
    }

    // DROP EFFECTS
    @HostListener('drop', ['$event']) onDrop(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        for (let i of this.fileHoverEffect){
            this.formUploader.nativeElement.classList.remove(i);
        }

        // Check if files exist
        this.files = event.dataTransfer?.files || null;
        if (!this.files){
            console.log('No files dropped'); 
            this.showErrorMessage('No files dropped', 7000);
            return;
        }

        // Process files
        this.processFiles(this.files);
    }
}
