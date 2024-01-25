import streamlit as st
import folium
from geopy.geocoders import Nominatim
from streamlit_folium import folium_static
import openrouteservice
from openrouteservice import client
import yaml

# Load configuration variables
with open('config.yml', 'r') as file:
    config_vars = yaml.safe_load(file)

# Configuration for OpenRouteService
ors_client = client.Client(key=config_vars['openroute_api_key'])

def main():
    st.title("Catchment Area Generator")
    
    # User inputs
    address = st.text_input("Enter the Address")
    radius_type = st.selectbox("Radius Type", ["Distance (miles)", "Drive Time (minutes)"])
    radius = st.number_input(f"Enter Radius in {radius_type.split()[1]}", min_value=1, value=10)

    if st.button("Generate Catchment Area"):
        location = geocode_address(address)
        if location:
            catchment_map = folium.Map(location=[location.latitude, location.longitude], zoom_start=13)
            
            if radius_type == "Distance (miles)":
                # Convert miles to meters for folium
                radius_meters = radius * 1609.34
                draw_circle(catchment_map, location, radius_meters)
            elif radius_type == "Drive Time (minutes)":
                draw_drive_time_area(catchment_map, location, radius, ors_client)

            folium_static(catchment_map)
        else:
            st.error("Could not geocode the address. Please try another address.")

def draw_circle(map_object, location, radius):
    """Draw a circle on the map."""
    folium.Circle(
        location=[location.latitude, location.longitude],
        radius=radius,
        color='blue',
        fill=True,
        fill_color='blue',
        fill_opacity=0.2
    ).add_to(map_object)

def draw_drive_time_area(map_object, location, drive_time, client):
    """Draw an area based on drive time."""
    coordinates = [[location.longitude, location.latitude]]
    params = {
        'locations': coordinates,
        'range': [drive_time * 60],  # Convert minutes to seconds
        'range_type': 'time'
    }
    response = client.isochrones(**params)
    folium.GeoJson(response).add_to(map_object)

def geocode_address(address):
    """Geocode an address using Nominatim."""
    geolocator = Nominatim(user_agent="streamlit_catchment_app")
    try:
        return geolocator.geocode(address)
    except:
        return None

if __name__ == "__main__":
    main()
