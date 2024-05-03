# Catchment Area Explorer
The Catchment Area Explorer is a Streamlit application designed to allow users to define custom catchment areas around any U.S. location. It leverages open-source data to overlay demographic and Points of Interest (POI) data within these areas, providing valuable insights for site planning, marketing, and research purposes.

## Features
- Generate catchment areas by distance or drive time around any address.
- Overlay demographic data from the U.S. Census.
- Display Points of Interest (POIs) within the catchment area.
- Interactive maps with folium for visual analysis.

## Data Sources (all 100% open-source)
- Nominatim: For geocoding addresses.
- OpenStreetMap: For geographical data and POIs.
- U.S. Census Bureau: For demographic data and census-defined geometries.
- OpenRouteService: For calculating drive times.

## Deployment
This app is deployed on Streamlit Cloud. Access it here: https://catchment-area-explorer.streamlit.app/ 

## Local Setup
1. Clone this repository.
2. Install dependencies: pip install -r requirements.txt
3. Add required API keys to `.streamlit/secrets.toml` (see [cloud_app.py](https://github.com/toratommy/catchment-area-app/blob/main/cloud_app.py) for required secrets)
4. Run the app: streamlit run cloud_app.py
Note: utility functions/classes can be found in the [src](https://github.com/toratommy/catchment-area-app/tree/main/src) folder

## Configuration
Configuration settings (API keys, data year, etc.) are located in config.yml. Customize this file as needed for your deployment.

For more detailed instructions, please refer to the "How It Works" tab within the app.

