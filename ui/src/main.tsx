import { render } from "preact";

import { App } from "./App";
import "./styles.css";

const root = document.getElementById("app");
if (!root) throw new Error("Mukha root element '#app' is missing.");

render(<App />, root);
