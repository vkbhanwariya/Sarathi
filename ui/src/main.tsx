import { render } from "preact";

import { App } from "./App";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

const root = document.getElementById("app");
if (!root) throw new Error("Mukha root element '#app' is missing.");

render(<App />, root);
