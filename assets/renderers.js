window.dashAgGridComponentFunctions = window.dashAgGridComponentFunctions || {};

window.dashAgGridComponentFunctions.TeamRenderer = function(props) {
    return React.createElement(
        "div",
        { style: { display: "flex", alignItems: "center", gap: "8px" } },
        React.createElement("img", { src: props.data.logo, style: { width: "24px", height: "24px", objectFit: "contain" } }),
        React.createElement("span", null, props.value)
    );
};

window.dashAgGridComponentFunctions.HomeRenderer = function(props) {
    return React.createElement(
        "div",
        { style: { display: "flex", alignItems: "center", gap: "8px", justifyContent: "flex-end" } },
        React.createElement("span", null, props.value),
        React.createElement("img", { src: props.data.home_logo, style: { width: "24px", height: "24px", objectFit: "contain" } })
    );
};

window.dashAgGridComponentFunctions.AwayRenderer = function(props) {
    return React.createElement(
        "div",
        { style: { display: "flex", alignItems: "center", gap: "8px" } },
        React.createElement("img", { src: props.data.away_logo, style: { width: "24px", height: "24px", objectFit: "contain" } }),
        React.createElement("span", null, props.value)
    );
};

window.dashAgGridComponentFunctions.FormRenderer = function(props) {
    var colors = { W: "#2e7d32", D: "#b07d00", L: "#b71c1c", N: "#dddddd"};
    var text_colors = { W: "#ffffff", D: "#ffffff", L: "#ffffff", N: "#dddddd"};
    var letters = (props.value || "").split("");
    return React.createElement(
        "div",
        { style: { display: "flex", gap: "4px", height: "100%", textAlign: "center", width: "18px", justifyContent: "flex-start", flexDirection: "row", alignItems: "center" } },
        letters.map(function(r, i) {
            return React.createElement(
                "span",
                {
                    key: i,
                    style: {
                        background: colors[r] || "#999",
                        color: text_colors[r] || "#eeeeee",
                        borderRadius: "3px",
                        fontSize: "11px",
                        fontWeight: "bold",
                        width: "20px",
                        height: "20px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                    }
                },
                r
            );
        })
    );
};