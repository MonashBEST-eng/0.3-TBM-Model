import express from 'express';
import fileUpload, { UploadedFile } from 'express-fileupload';
import { processCSV } from './helper_functions'


const PORT_NUMBER = 4200;

const app = express();
let result: { accept?: boolean }[] = [];

// Middlewares
app.use(express.static("./dist/csv-parser/browser"));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(fileUpload());

app.listen(PORT_NUMBER, function () {
    console.log(`listening on port ${PORT_NUMBER}`);
});

// Upload csv files
app.post('/api/upload', (req: express.Request, res: express.Response) => {
    try {
        // Check if files exist
        if (!req.files) {res.status(404).send({ accept: false, message: 'File Upload Failed, file does not exist' }); return;}

        // Get files from request
        let files: UploadedFile | UploadedFile[] = req.files.file;
        result = [];

        // Checks file upload
        // Single file
        if (!Array.isArray(files)) {
            if (!files) {res.status(404).send({ accept: false, message: 'File Upload Failed, file does not exist' }); return;}
            result.push(processCSV(files))

        // Multiple files
        }else{
            // Iterate through each file sent
            files.forEach((file: UploadedFile) => {
                if (!file) {res.status(404).send({ accept: false, message: 'File Upload Failed, a file provided does not exist' }); return;}
                result.push(processCSV(file));
            });
        }
        console.log(result);


        // Validate csv files
        result.forEach((resultant) => {
            if (!resultant || !resultant.accept) { 
                res.status(404).send({ accept: false, message: 'Invalid csv format. Csv must be of the form: {Number Number}' }); 
                return;
            }

            // Delete accept key from object after validation
            delete resultant.accept;
        });

        res.status(200).send({ accept: true, message: 'File Uploaded Successfully', data: result });
    } catch (error) {
        console.log(error);
    }
});

// Get api upload results
app.get('/api/upload', (req: express.Request, res: express.Response) => {
    res.status(200).send(result);
});

// Delete files upon reload
app.get('/api/reload', (req: express.Request, res: express.Response) => {
    result = [];
    res.status(200).send({ accept: true, message: 'Files deleted successfully' });
});