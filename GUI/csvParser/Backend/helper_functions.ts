import { UploadedFile } from "express-fileupload";

let findMean = (data : number[]) : number => {
    let sum = 0;
    for (let num of data) {
        sum += num;
    }
    return sum / data.length;
};

let sumProductDifferences = (xi : number[], xMean : number, yi: number[], yMean: number) : number => {
    let res = 0;
    xi.forEach(( xVal, index) => {
        let yVal = yi[index];
        let sumX = xVal - xMean;
        let sumY = yVal - yMean;
        res += sumX * sumY;
    })
    return res;
};

let sumSquareDifference = (data : number[], mean : number) : number => {
    let sum = 0;
    for (let num of data) {
        sum += Math.pow(num - mean, 2);
    }
    return sum;
};

let findDataVariance = (data : number[]) : number => {
    let mean = findMean(data);
    let sumSquareDiff = sumSquareDifference(data, mean);
    let variance = sumSquareDiff / (data.length - 1);
    return variance;
};

let findRegressionLine = (xData : number[], yData : number[]) : {a:number, b:number} => {
    let xMean = findMean(xData);
    let yMean = findMean(yData);

    let sumProductDiff = sumProductDifferences(xData, xMean, yData, yMean);
    let sumSquareDiffX = sumSquareDifference(xData, xMean);

    let bVal = sumProductDiff / sumSquareDiffX;
    let aVal = yMean - bVal * xMean;

    return {a: aVal, b: bVal};
};

let findSumResidualsSquared = (xData : number[], yData : number[]) : number => {
    let values: {a:number, b:number} = findRegressionLine(xData, yData);
    let SSR = 0;

    yData.forEach((y, index) => {
        let yHat = values.a + values.b * xData[index];
        let residual = y - yHat;
        SSR += Math.pow(residual, 2);
    })

    return SSR;
};

let findR2 = (xData : number[], yData : number[]) : number => {
    let SST = sumSquareDifference(yData, findMean(yData));
    let SSR = findSumResidualsSquared(xData, yData);
    let R2 = 1 - (SSR / SST);
    return R2;
};

// Parse CSV file into time and force arrays
let processCSV = (file: UploadedFile) : object => {
    let fileName: string = file.name;
    let csvData: string = file.data.toString('utf8');
    let timeArr: number[] = [];
    let forceArr: number[] = [];

    if (csvData === '') {
        console.log('Empty file');
        return {accept: false};
    }

    for (const line of csvData.split('\n')) {
        // Check if line fits format (NUM NUM)
        // MAYBE: Add checks for negative numbers and decimals
        // Diff match for white space at end of csv 
        if (!line.match(/\d+ \d+/)) { 
            console.log('Invalid format');
            return {accept: false};
        }

        // Split line into data
        const [time, force] = line.split(' ');
        timeArr.push(Number(time));
        forceArr.push(Number(force));

        console.log(time, force);
    }

    let variance = findDataVariance(forceArr);
    let R2 = findR2(timeArr, forceArr);
    let objResult = {accept: true, 
                    name: fileName,
                    timeArr : timeArr ? timeArr : null, 
                    forceArr: forceArr ? forceArr : null, 
                    variance: variance ? variance : null,
                    R2: R2 ? R2 : null
                };

    return objResult;
};

export { processCSV };