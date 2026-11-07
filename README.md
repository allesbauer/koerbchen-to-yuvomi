# koerbchen-to-yuvomi
 I try to copy my recipes from Körbchen to Yuvomi. Unfortunately, Körbchen cannot be integrated directly into Yuvomi, and there is no machine-readable export function for Körbchen or import function in Yuvomi. Therefore, the script uses a JSON file that is loaded when the Körbchen web app is accessed and transforms it so that it can be imported via Yuvomi's openAPI.

## How to use it
Log in to the Körbchen web app using your credentials. Open the developer options in your web browser and go to Network Analysis. Set the filter to XHR and reload the page. Look for a GET request to the domain firestore.googleapis.com and save the response to a file. The response file should contain all the recipes (if you're unsure, search for a recipe name in the response; mine was over 1MB large, so easy to find). Remove all tokens, and then convert the section containing the recipes into a JSON file named koerbchen_recipes.json. This JSON file must be in the same folder as the script. Next, enter the Yuvomi URL and the API token into the script. When run without any parameters, the script checks whether all conditions are met. The --limit X parameter checks only the first X recipes (the default is 1,000). The --apply parameter executes the request on the Yuvomi system.

## Whats missing
* Currently it is not possible to transfer pictures into Yuvomi.
* The Messages from the script are currently in german only.

## Disclaimer
No liability is assumed for any losses. The script was developed with some assistance from AI.