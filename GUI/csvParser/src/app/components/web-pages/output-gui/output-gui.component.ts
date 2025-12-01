import { Component, OnInit, ViewChild } from '@angular/core';
import { FileParserService } from '../../../services/file-parser/file-parser.service';
import { Router, RouterLink} from '@angular/router';
import {
    NgApexchartsModule,
    ChartComponent,
    ApexAxisChartSeries,
    ApexChart,
    ApexDataLabels,
    ApexTitleSubtitle,
    ApexStroke,
    ApexGrid
} from "ng-apexcharts";
import { DecimalPipe } from '@angular/common';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { faSquareCaretLeft, faSquareCaretRight } from '@fortawesome/free-solid-svg-icons'; 
import { BackButtonComponent } from '../../ui/back-button/back-button.component';
  
export type ChartOptions = {
    series: ApexAxisChartSeries;
    chart: ApexChart;
    labels: number[];
    dataLabels: ApexDataLabels;
    grid: ApexGrid;
    stroke: ApexStroke;
    title: ApexTitleSubtitle;
  };

export type resultObject = {
    name: string;
    timeArr: number[];
    forceArr: number[];
    variance: number;
    R2: number;
};

@Component({
  selector: 'app-output-gui',
  imports: [NgApexchartsModule, DecimalPipe, FontAwesomeModule, BackButtonComponent],
  templateUrl: './output-gui.component.html',
  styleUrl: './output-gui.component.scss'
})
export class OutputGuiComponent implements OnInit{
    faSquareCaretLeft = faSquareCaretLeft;
    faSquareCaretRight = faSquareCaretRight;
    resultObject: resultObject[] = [];  
    index: number = 0;

    public chartOptions: ChartOptions[] | any = [];  
    @ViewChild("chart") chart: ChartComponent = new ChartComponent;

    constructor(private fileParser: FileParserService, private router : Router) {}

    ngOnInit(): void {
        // Get data from fileParser service
        this.fileParser.getData().subscribe(res => {
            if (res === null || res === undefined) {
                this.router.navigate(['/invalid']);
                return;
            };
            console.log(res);
            this.resultObject = res as resultObject[];
            for(let data of (res as resultObject[])) {
                this.chartOptions.push(this.setUpGraph(data));
            }
        });
    }

    setUpGraph(res: resultObject) : Partial<ChartOptions> | any{
        console.log(res.forceArr);
        console.log(res.timeArr);
        let chartOptions = {
            series: [
            {
                name: "Force",
                data: res.forceArr
            }
            ],
            labels: res.timeArr,
            chart: {
                type: "line",
                zoom: {
                    enabled: false
                }
            },
            dataLabels: {
                enabled: false
            },
            stroke: {
                curve: "straight"
            },
            title: {
                text: res.name,
                align: "left"
            },
            grid: {
                row: {
                    colors: ["#f3f3f3", "transparent"],
                    opacity: 0.5
                }
            },
        };
        return chartOptions;
    }

    back(){
        this.router.navigate(['/']);
    }

    nextGraph(){
        if(this.index < this.resultObject.length-1){
            this.index++;
        }
    }

    prevGraph(){
        if(this.index > 0){
            this.index--;
        }
    }

}
