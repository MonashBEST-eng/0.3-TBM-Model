// Helper function to parse CSV into array of objects
function parseCSV(text) {
    const lines = text.trim().split("\n");
    const headers = lines[0].split(",");
    return lines.slice(1).map(line => {
        const values = line.split(",");
        const obj = {};
        headers.forEach((h, i) => obj[h.trim()] = values[i].trim());
        return obj;
        });
}

// Event listener for CSV upload
document.getElementById("csvInput").addEventListener("change", function (e) {
    const file = e.target.files[0];
    const reader = new FileReader();
    reader.onload = function (e) {
    const csvData = parseCSV(e.target.result);
    renderComponents(csvData);
    };
    reader.readAsText(file);
});

// Renders the ECU boxes and computes power usage
function renderComponents(data) {
    const componentsBox = document.getElementById("componentsBox");
    componentsBox.innerHTML = "";

    const elements = {}; // Stores DOM elements by Ref.
    let totalPower = 0;
    let maxTotalPower = 0;

    // Create visual boxes for each ECU
    data.forEach(item => {
    const box = document.createElement("div");
    box.className = "component";
    box.innerHTML = `
        <strong>${item["Ref."]}</strong><br>
        Nominal - ${item["Nominal Power (W)"]}W, ${item["Nominal Voltage (V)"]}V, ${item["Nominal Current (A)"]}A<br>
        Max - ${item["Max Power (W)"]}W, ${item["Max Voltage (V)"]}V, ${item["Max Current (A)"]}A
    `;

    const power = parseFloat(item["Nominal Power (W)"]);
    const maxPower = parseFloat(item["Max Power (W)"]);
    if (!isNaN(power)) totalPower += power;
    if (!isNaN(maxPower)) maxTotalPower += maxPower;

    elements[item["Ref."]] = box;
    componentsBox.appendChild(box);
    });

    // Update total power
    document.getElementById("totalPower").innerText = `${Math.round(totalPower * 100) / 100}W`;
    document.getElementById("maxTotalPower").innerText = `${Math.round(maxTotalPower * 100) / 100}W`;

    // // After render, draw lines between parent and child components
    // drawLines(data, elements);
}

// // Draws lines between parent and child components using canvas
// function drawLines(data, elements) {
//     const canvas = document.getElementById("connectionCanvas");
//     const ctx = canvas.getContext("2d");
//     canvas.width = window.innerWidth;
//     canvas.height = window.innerHeight;
//     ctx.clearRect(0, 0, canvas.width, canvas.height);
//     ctx.strokeStyle = "black";

//     data.forEach(item => {
//     const parentRef = item["Parent"];
//     const childRef = item["Ref."];
//     const parentBox = elements[parentRef];
//     const childBox = elements[childRef];
//     if (parentBox && childBox) {
//         const pRect = parentBox.getBoundingClientRect();
//         const cRect = childBox.getBoundingClientRect();
//         const pX = pRect.left + pRect.width / 2;
//         const pY = pRect.top + pRect.height / 2;
//         const cX = cRect.left + cRect.width / 2;
//         const cY = cRect.top + cRect.height / 2;

//         ctx.beginPath();
//         ctx.moveTo(pX, pY);
//         ctx.lineTo(cX, cY);
//         ctx.stroke();
//     }
//     });
// }