import streamDeck from "@elgato/streamdeck";

import { TimerAction } from "./actions/timer.js";

streamDeck.logger.setLevel("info");

// Register the timer action, then connect to the Stream Deck.
streamDeck.actions.registerAction(new TimerAction());

streamDeck.connect();
