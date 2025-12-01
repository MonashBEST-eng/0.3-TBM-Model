import { Component, OnInit} from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Router } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
    title = 'csvParser';

    constructor(private router: Router) {}

    // WIP dont know how to fix reload output gui bug
    ngOnInit() {
        // this.router.navigate(['']);
    }

    
}
