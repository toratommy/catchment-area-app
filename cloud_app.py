import streamlit as st
from streamlit_extras.app_logo import add_logo
import folium
from streamlit_folium import folium_static
from openrouteservice import client
import pandas as pd
import geopandas as gpd
from census import Census
import time
from utils import *
import pickle

# TO DO's
# Add sum of census var under total population. If not a pop var, display N/A (variable does not represent pop.)
# Add caching
# Finalize docs

# Initialize configuration variables
ors_client = client.Client(key=st.secrets['openroute_api_key'])
census_year = st.secrets['census_year']
census_api_key =  st.secrets['census_api_key']

def main():
    st.title("Catchment Area Explorer")
    tab1, tab2, tab3, tab4 = st.tabs(["Generate Catchment Area", "Demographic Overlay", "POI Overlay", "How It Works"])
    # User inputs
    with st.sidebar:
        st.image('https://assets-global.website-files.com/659c81c957e77aeea1809418/65b2f184ee9f42f63bc2c651_TORA%20Logo%20(No%20Background)-p-800.png')
        st.subheader('About')
        st.caption("""📍 Welcome to Catchment Area Explorer! Generate a custom catchment 
               area defined by distance or drive time around any location in the US. 
               Uncover insights by overlaying key demographic and POI data within your catchemnt area. 
               Utilizing 100% open-source data and tools!
               """
        )
        st.caption("""Like this app? Check out what else we're up to at www.torainsights.ai""")
        st.divider()
        st.subheader('Get started: define your catchment area')
        address = st.text_input("Enter the Address", value='2834 N. Ashland Ave, Chicago, IL 60657')
        radius_type = st.selectbox("Enter Radius Type", ["Distance (miles)", "Drive Time (minutes)"], index = 1)
        radius = st.number_input(f"Enter Radius in {radius_type.split()[1]}", min_value=1, max_value = 100, value=10)
        generate_catchment = st.button("Generate Catchment Area")
        st.divider()

    with tab1:
        st.subheader('Catchment area charateristics')
        # geocode location and generate catchment area
        location = geocode_address(address)
        if location:
            catchment_map = folium.Map(location=[location.latitude, location.longitude], zoom_start=13)
            if generate_catchment:
                with st.spinner('Generating catchment area...'):
                    if radius_type == "Distance (miles)":
                        # Convert miles to meters for folium
                        radius_meters = radius * 1609.34
                        st.session_state.user_poly, st.session_state.bounds = draw_circle(catchment_map, location, radius_meters)
                    elif radius_type == "Drive Time (minutes)":
                        st.session_state.user_poly, st.session_state.bounds = draw_drive_time_area(catchment_map, location, radius, ors_client)
                catchment_size = calculate_area_sq_miles(st.session_state.user_poly)
                
                location_caption = 'Location: '+address
                if radius_type == 'Distance (miles)':
                    radius_caption = 'Catchment radius: '+str(radius)+' miles'
                else: 
                    radius_caption = 'Catchment radius: '+str(radius)+' minute drive'
                catchment_size_caption = "Catchment size: "+str(catchment_size)+" square miles"
                map_caption = location_caption + ' | ' + radius_caption + ' | ' + catchment_size_caption
                st.caption(map_caption)
            else: 
                st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')
            folium_static(catchment_map)
        else:
            st.error("Could not geocode the address. Please try another address.")

    with tab2:
        st.subheader('Overlay demographic data within your catchment')
        api_url = "https://api.census.gov/data/{0}/acs/acs5".format(census_year)
        variables_df = fetch_census_variables(api_url)
        filters_dict = variables_df.groupby('Variable Group')['Variable Name'].apply(list).to_dict()
        var_group = st.selectbox('Choose Census Variable Group', options=(v for v in filters_dict.keys()),index=445)
        var_name = st.selectbox('Choose Census Variable Name', options=filters_dict[var_group])
        normalization = st.radio("Normalize by Population?",["No", "Yes"],index=0)

        plot_census_data = st.button("Plot Demographic Data")
        st.divider()
        if "user_poly" in st.session_state:
            catchment_size = calculate_area_sq_miles(st.session_state.user_poly)
            location_caption = 'Location: '+address
            if radius_type == 'Distance (miles)':
                radius_caption = 'Catchment radius: '+str(radius)+' miles'
            else: 
                radius_caption = 'Catchment radius: '+str(radius)+' minute drive'
            catchment_size_caption = "Catchment size: "+str(catchment_size)+" square miles"
            map_caption = location_caption + ' | ' + radius_caption + ' | ' + catchment_size_caption
            st.caption(map_caption)
        else:
            st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')  
        #fetch and plot census data
        if plot_census_data:
            if "user_poly" in st.session_state:
                with st.spinner('Fetching demographic data to plot...'):
                    variables = variables_df[(variables_df['Variable Name']==var_name) & (variables_df['Variable Group']==var_group)]['variable'].to_list()
                    census_api = Census(census_api_key) 

                    # Load state boundaries and identify intersecting states
                    user_gdf = gpd.GeoDataFrame(index=[0], crs='EPSG:4326', geometry=[st.session_state.user_poly])
                    states_gdf = load_state_boundaries(census_year)
                    intersecting_state_codes = find_intersecting_states(user_gdf, states_gdf)

                    # Calculate overlapping tracts for intersecting states
                    overlapping_tracts = calculate_overlapping_tracts(user_gdf, intersecting_state_codes, census_year)

                    # Fetch census data for overlapping tracts
                    census_data = fetch_census_data_for_tracts(census_api, census_year, variables, overlapping_tracts, normalization)

                    plot_census_data_on_map(catchment_map, st.session_state.bounds, overlapping_tracts, census_data, variables[0], var_name, normalization)

                    # Generate distribution plot
                    fig = create_distribution_plot(census_data, variables, var_name, normalization)
                    
                    total_population = fetch_census_data_for_tracts(census_api, census_year, ['B01003_001E'], overlapping_tracts, 'No')['B01003_001E'].sum()
                    st.caption('Estimated total population: '+str(total_population) )
                    map_caption = 'Heatmap of '+var_group+' - '+var_name
                    st.caption(map_caption)
                    if "bounds" in st.session_state:
                        catchment_map.fit_bounds(st.session_state.bounds)
                    folium_static(catchment_map)
                    st.divider()
                    st.subheader("Distribution plot of selected census variable across your catchment area")
                    if ('Total:' in var_name) or ('Aggregate' in var_name):
                        st.caption('Sum (across entire catchment) of ***'+var_name+'***: '+str(round(sum(census_data[variables[0]]),0)))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.error('Must generate catchment area first before overlaying census data. Please define and generate your catchment area using the left control panel.')
        else:
            if "bounds" in st.session_state:
                catchment_map.fit_bounds(st.session_state.bounds)
            folium_static(catchment_map)
        
    with tab3:
        st.subheader('Overlay POI data within your catchment')
        # read in list of amenities
        with open('amenities.pkl', 'rb') as f:
            amenity_list = pickle.load(f)
        poi_categories = st.multiselect('Select POI categories to map',amenity_list)
        poi_map_type = st.radio('Choose map type:', ['POI markers','Heatmap (POI density)'])
        plot_poi_data = st.button("Plot POI data")
        st.divider()
        if "user_poly" in st.session_state:
            catchment_size = calculate_area_sq_miles(st.session_state.user_poly)
            location_caption = 'Location: '+address
            if radius_type == 'Distance (miles)':
                radius_caption = 'Catchment radius: '+str(radius)+' miles'
            else: 
                radius_caption = 'Catchment radius: '+str(radius)+' minute drive'
            catchment_size_caption = "Catchment size: "+str(catchment_size)+" square miles"
            map_caption = location_caption + ' | ' + radius_caption + ' | ' + catchment_size_caption
            st.caption(map_caption)
        else:
            st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')  
        #fetch and plot poi data
        if plot_poi_data:
            if "user_poly" in st.session_state:
                with st.spinner('Fetching POI data to plot...'):
                    time.sleep(5)
                    pois_gdf = fetch_poi_within_catchment(st.session_state.user_poly, poi_categories)
                display_poi_counts(pois_gdf)
                catchment_map = plot_poi_data_on_map(pois_gdf, st.session_state.user_poly, poi_map_type)
                catchment_map.fit_bounds(st.session_state.bounds)
                folium_static(catchment_map)
            else:
                st.error('Must generate catchment area first before overlaying census data. Please define and generate your catchment area using the left control panel.')
        else:
            if "bounds" in st.session_state:
                catchment_map.fit_bounds(st.session_state.bounds)
            folium_static(catchment_map)

    with tab4:
        st.subheader('Overview')
        st.caption('''The "Catchment Area Explorer" app, designed with Streamlit, enables users to create custom catchment areas 
                   around specified U.S. locations based on distance or drive time. It integrates open-source data and tools, 
                   including OSMnx for geospatial analysis and OpenStreetMap for detailed mapping and Points of Interest (POIs). 
                   The app leverages the Census API for demographic overlays and OpenRouteService for drive time analysis, 
                   providing insights into demographics and POIs within the defined areas. It's structured across tabs for generating 
                   catchment areas, overlaying demographic data, and displaying POIs, all powered by open-source technologies for 
                   comprehensive, data-driven insights.
                   ''')
        st.subheader('Step-by-step guide:')
        st.subheader('Data source documentation:')
        st.caption("""Like this app? Check out what else we're up to at www.torainsights.ai""")
        
# Run app

if __name__ == "__main__":
    main()
