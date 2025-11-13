function updateClock() {
    let now = new Date();
    document.getElementById("clock").innerText =
        now.toLocaleTimeString();
}

async function updateInfo() {
    try {
        let controller = new AbortController();
        setTimeout(() => controller.abort(), 2000);

        let r = await fetch("/info", { signal: controller.signal });
        let data = await r.json();

        document.getElementById("cpu").innerText = data.cpu;
        document.getElementById("battery").innerText = data.battery;

    } catch (e) {
        document.getElementById("cpu").innerText = "??";
        document.getElementById("battery").innerText = "??";
    }
}

async function updateNodes() {
    try {
        let r = await fetch("/nodes");
        let nodes = await r.json();

        let list = document.getElementById("node-list");
        list.innerHTML = "";

        nodes.forEach(n => {
            let item = document.createElement("li");
            item.innerText = `${n.id} — CPU: ${n.cpu}% — Battery: ${n.battery}%`;
            list.appendChild(item);
        });

    } catch (e) {
        console.log("nodes update failed");
    }
}

setInterval(() => {
    updateClock();
    updateInfo();
    updateNodes();
}, 1000);

updateClock();
updateInfo();
updateNodes();
