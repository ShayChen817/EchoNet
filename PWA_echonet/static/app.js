// --------------------
// AUTO-REFRESH TIMERS
// --------------------
setInterval(updateInfo, 2000);
setInterval(updateNodes, 2000);


// --------------------
// FETCH SELF METRICS
// --------------------
async function updateInfo() {
    try {
        const res = await fetch("/info");
        const data = await res.json();

        document.getElementById("cpu").textContent = data.cpu.toFixed(1);
        document.getElementById("battery").textContent = data.battery ?? "N/A";
        document.getElementById("load").textContent = `${data.load}/${data.max_load}`;
        document.getElementById("health").textContent = data.health.toFixed(2);

    } catch (e) {
        console.log("info fetch error:", e);
    }
}


// --------------------
// FETCH NODE LIST
// --------------------
async function updateNodes() {
    try {
        const res = await fetch("/nodes");
        const nodes = await res.json();

        const list = document.getElementById("node-list");
        list.innerHTML = "";

        for (const node of nodes) {
            const li = document.createElement("li");

            li.innerHTML = `
                <div class="node-box">
                    <strong>${node.id}</strong><br>
                    ip: ${node.ip}:${node.port}<br>
                    skills: ${node.skills.join(", ")}<br>
                    cpu: ${node.metrics.cpu}%<br>
                    battery: ${node.metrics.battery ?? "N/A"}<br>
                    load: ${node.metrics.load}/${node.metrics.max_load}<br>
                    health: ${node.metrics.health.toFixed(2)}<br>
                    last seen: ${node.last_seen}
                </div>
            `;

            list.appendChild(li);
        }

        document.getElementById("debug").textContent =
            JSON.stringify(nodes, null, 2);

    } catch (e) {
        console.log("node fetch error:", e);
    }
}
