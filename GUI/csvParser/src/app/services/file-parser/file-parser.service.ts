import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';

const API_URL = 'http://localhost:4200/api';
const httpOptions = {
    headers: new HttpHeaders({ 'Content-type': 'text/csv' })
};
@Injectable({
  providedIn: 'root'
})
export class FileParserService {

    constructor(private http: HttpClient) {}

    uploadFiles(files: File[]) {
        const uploadedFile = new FormData();
        files.forEach(file => {
            uploadedFile.append('file', new Blob([file], { type: 'text/csv' }), file.name);
        });
        return this.http.post(API_URL + '/upload', uploadedFile);
    }

    getData() {
        return this.http.get(API_URL + '/upload');
    }

    reload() {
        return this.http.get(API_URL + '/reload');
    }
}
