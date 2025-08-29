// Set current date in print header
document.addEventListener('DOMContentLoaded', function() {
    const now = new Date();
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    const printDate = document.getElementById('printDate');
    if (printDate) {
        printDate.textContent = now.toLocaleDateString('en-US', options);
    }
});

function printReport() {
    // Update date just before printing
    const now = new Date();
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    document.getElementById('printDate').textContent = now.toLocaleDateString('en-US', options);

    window.print();
}
