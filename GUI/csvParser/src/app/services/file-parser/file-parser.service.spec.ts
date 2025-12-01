import { TestBed } from '@angular/core/testing';

import { FileParserService } from './file-parser.service';

describe('FileParserService', () => {
  let service: FileParserService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(FileParserService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
