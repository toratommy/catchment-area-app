import streamlit as st
from streamlit_extras.app_logo import add_logo
import folium
from streamlit_folium import folium_static
from openrouteservice import client
import pandas as pd
import geopandas as gpd
from census import Census
import time
from src.utils import *
import yaml
import pickle
from folium.plugins import Fullscreen
from catchment_area import CatchmentArea

# TO DO:
# refactor to be object oriented
# scale down for small cathcmnet areas; use to total pop returned value in ORS. also update map to include only in catchment
# add bar chart to POI page
# add pop density to POI page
# add distance to nearest on POI page
# add census data profiles
# add real estate data

# Load configuration variables
with open('config.yml', 'r') as file:
    config_vars = yaml.safe_load(file)

# Initialize configuration variables
ors_client = client.Client(key=config_vars['openroute_api_key'])
census_year = config_vars['census_year']
census_api_key =  config_vars['census_api_key']

def main():
    # set theme
    st._config.set_option(f'theme.base' ,"light" )
    st._config.set_option(f'theme.primaryColor',"#f63366")
    st._config.set_option(f'theme.backgroundColor',"#FFFFFF")
    st._config.set_option(f'theme.secondaryBackgroundColor', "#f0f2f6")
    st._config.set_option(f'theme.textColor',"#262730")

    st.title("Catchment Area Explorer")
    tab1, tab2, tab3, tab4 = st.tabs(["Generate Catchment Area", "Demographic Overlay", "POI Overlay", "How It Works"])
    # User inputs
    with st.sidebar:
        st.image('https://assets-global.website-files.com/659c81c957e77aeea1809418/65b2f184ee9f42f63bc2c651_TORA%20Logo%20(No%20Background)-p-800.png')
        st.subheader('About')
        st.caption("""📍 Welcome to Catchment Area Explorer! Generate a custom catchment 
               area defined by distance or drive time around any location in the US. 
               Uncover insights by overlaying key demographic and POI data within your catchment area. 
               Utilizing 100% open-source data and tools!
               """
        )
        st.caption("""Like this app? Check out what else we're up to at www.torainsights.ai""")
        st.divider()
        st.subheader('Get started: define your catchment area')
        address, radius_type, travel_profile, radius = make_catchment_area_selections()
        generate_catchment = st.button("Generate Catchment Area")
        st.divider()

    with tab1:
        st.subheader('Catchment area characteristics')
        st.session_state.tile_layer_value, st.session_state.tile_layer_type = map_tile_layer_selections()

        # Initialize 'location' in session state if not already present
        st.session_state.location = geocode_address(address)
        
        # Initialize the map only if 'location' is successfully geocoded
        if st.session_state.location:
            if 'catchment_map' not in st.session_state or generate_catchment:
                # Initialize map centered on the geocoded location
                st.session_state.catchment_map = folium.Map(location=[st.session_state.location.latitude, st.session_state.location.longitude], zoom_start=13)
            update_map_layer(st.session_state)
            # Fullscreen plugin for map expansion
            Fullscreen(position="topright", title="Expand me", title_cancel="Exit me", force_separate_button=True).add_to(st.session_state.catchment_map)

            # Generate catchment area
            if generate_catchment:
                with st.spinner('Generating catchment area...'):
                    catchment_area = CatchmentArea(st.session_state.location, 
                                                   radius_type, 
                                                   radius,   
                                                   travel_profile,
                                                   ors_client)
                    catchment_area.generate_geometry()
                    st.session_state.catchment_area = catchment_area
                    plot_catchment_area(st.session_state)

            if "catchment_area" in st.session_state:
                catchment_size = calculate_area_sq_miles(st.session_state.catchment_area.geometry)
                location_caption = 'Location: '+address
                if radius_type == 'Distance (miles)':
                    radius_caption = 'Catchment radius: '+str(radius)+' miles'
                else: 
                    radius_caption = 'Catchment radius: '+str(radius)+' minutes by '+travel_profile.lower()
                    total_pop_caption = 'Estimated catchment population: ' + '{:,}'.format(int(st.session_state.catchment_area.iso_properties['total_pop']))
                catchment_size_caption = "Catchment size: "+'{:,}'.format(catchment_size)+" square miles"
                map_caption1 = location_caption + ' | ' + radius_caption 
                if "catchment_area.iso_properties" in st.session_state and radius_type == 'Travel time (minutes)':
                    map_caption2 = catchment_size_caption + ' | ' + total_pop_caption
                else: 
                    map_caption2 = catchment_size_caption 
                st.caption(map_caption1)
                st.caption(map_caption2)
            else:
                st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')

            # Display existing catchment area on map if available
            if 'catchment_area' in st.session_state:
                folium.GeoJson(st.session_state.catchment_area.geometry, style_function=lambda x: {'fillColor': 'blue', 'color': 'blue'}).add_to(st.session_state.catchment_map)
            
            folium_static(st.session_state.catchment_map)
        else:
            st.error("Could not geocode the address. Please try another address or check the geocoding service.")

    with tab2:
        st.subheader('Overlay demographic data within your catchment')
        api_url = "https://api.census.gov/data/{0}/acs/acs5".format(census_year)
        variables_df = fetch_census_variables(api_url)
        filters_dict = variables_df.groupby('Variable Group')['Variable Name'].apply(list).to_dict()
        var_group, var_name, normalization = make_census_variable_selections(filters_dict)
        plot_census_data = st.button("Plot Demographic Data")
        st.divider()
        if "catchment_area" in st.session_state:
            catchment_size = calculate_area_sq_miles(st.session_state.catchment_area.geometry)
            location_caption = 'Location: '+address
            if radius_type == 'Distance (miles)':
                radius_caption = 'Catchment radius: '+str(radius)+' miles'
            else: 
                radius_caption = 'Catchment radius: '+str(radius)+' minutes by '+travel_profile.lower()
            catchment_size_caption = "Catchment size: "+str(catchment_size)+" square miles"
            map_caption = location_caption + ' | ' + radius_caption + ' | ' + catchment_size_caption
            st.caption(map_caption)
        else:
            st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')  
        #fetch and plot census data
        if plot_census_data:
            if "catchment_area" in st.session_state:
                with st.spinner('Fetching demographic data to plot...'):
                    variables = variables_df[(variables_df['Variable Name']==var_name) & (variables_df['Variable Group']==var_group)]['variable'].to_list()
                    census_api = Census(census_api_key) 

                    # Load state boundaries and identify intersecting states
                    user_gdf = gpd.GeoDataFrame(index=[0], crs='EPSG:4326', geometry=[st.session_state.catchment_area.geometry])
                    states_gdf = load_state_boundaries(census_year)
                    intersecting_state_codes = find_intersecting_states(user_gdf, states_gdf)

                    # Calculate overlapping tracts for intersecting states
                    overlapping_tracts = calculate_overlapping_tracts(user_gdf, intersecting_state_codes, census_year)

                    # Fetch census data for overlapping tracts
                    census_data = fetch_census_data_for_tracts(census_api, census_year, variables, overlapping_tracts, normalization)

                    st.session_state.census_map = plot_census_data_on_map(st.session_state, overlapping_tracts, census_data, variables[0], var_name, normalization)

                    # Generate distribution plot
                    fig = create_distribution_plot(census_data, variables, var_name, normalization)
                    
                    total_population = fetch_census_data_for_tracts(census_api, census_year, ['B01003_001E'], overlapping_tracts, 'No')['B01003_001E'].sum()
                    if st.session_state.catchment_area.iso_properties and radius_type == 'Travel time (minutes)':
                        st.caption('Total population (across entire catchment): '+'{:,}'.format(int(st.session_state.catchment_area.iso_properties['total_pop'])))
                    else:
                        st.caption('Total population (across entire catchment): '+'{:,}'.format(int(total_population)))
                    if ('Total:' in var_name) or ('Aggregate' in var_name):
                        st.caption('Sum (across entire catchment) of `'+var_group+'` - `'+var_name+'`: '+f'{int(sum(census_data[variables[0]])):,}')
                    folium_static(st.session_state.census_map)
                    st.divider()
                    st.subheader("Distribution plot of selected census variable across your catchment area")
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.error('Must generate catchment area first before overlaying census data. Please define and generate your catchment area using the left control panel.')
        else:
            folium_static(st.session_state.catchment_map)
        
    with tab3:
        st.subheader('Overlay POI data within your catchment')
        # read in list of amenities
        with open('src/amenities.pkl', 'rb') as f:
            amenity_list = pickle.load(f)
        poi_categories, poi_map_type = make_poi_selections(amenity_list)
        plot_poi_data = st.button("Plot POI data")
        st.divider()
        
        if "catchment_area" in st.session_state:
            catchment_size = calculate_area_sq_miles(st.session_state.catchment_area.geometry)
            location_caption = 'Location: '+address
            if radius_type == 'Distance (miles)':
                radius_caption = 'Catchment radius: '+str(radius)+' miles'
            else: 
                radius_caption = 'Catchment radius: '+str(radius)+' minutes by '+travel_profile.lower()
            catchment_size_caption = "Catchment size: "+str(catchment_size)+" square miles"
            map_caption = location_caption + ' | ' + radius_caption + ' | ' + catchment_size_caption
            st.caption(map_caption)
        else:
            st.caption('No catchment generated. Use left control panel to define and generate your catchment area.')  
        #fetch and plot poi data
        if plot_poi_data:
            if "catchment_area" in st.session_state:
                with st.spinner('Fetching POI data to plot...'):
                    time.sleep(5)
                    pois_gdf = fetch_poi_within_catchment(st.session_state.catchment_area.geometry, poi_categories)
                display_poi_counts(pois_gdf)
                st.session_state.poi_map = plot_poi_data_on_map(pois_gdf, st.session_state, poi_map_type)
                st.session_state.poi_map.fit_bounds(st.session_state.bounds)
                folium_static(st.session_state.poi_map)
            else:
                st.error('Must generate catchment area first before overlaying census data. Please define and generate your catchment area using the left control panel.')
        else:
            folium_static(st.session_state.catchment_map)

    with tab4:
        st.subheader('Overview')
        st.markdown('''The "Catchment Area Explorer" app, designed with Streamlit, enables users to create custom catchment areas 
                   around specified U.S. locations based on distance or drive time. It integrates open-source data and tools, 
                   including OSMnx for geospatial analysis and OpenStreetMap for detailed mapping and Points of Interest (POIs). 
                   The app leverages the Census API for demographic overlays and OpenRouteService for drive time analysis, 
                   providing insights into demographics and POIs within the defined areas. It's structured across tabs for generating 
                   catchment areas, overlaying demographic data, and displaying POIs, all powered by open-source technologies for 
                   comprehensive, data-driven insights.
                   ''')
        st.subheader('Step-by-Step User Guide:')
        st.markdown('''1. Generate a Catchment Area: Using the left control panel, enter an address and radius (drive time or distance) to define your catchment area.
                    Upon clicking the `Generate Catchment Area` button, view your catchment area on the interactive map and adjust as needed by changing the 
                    parameters in the left control panel.
                    ''')
        st.markdown('''2. Overlaying Demographics: Next, navigate to the `Overlay Demographics` tab to plot population demographics within your catchment area. Select a variable of interest, 
                    and specify whether or not you'd like to normalize by population (i.e., plotting percent of population with selected variable vs plotting total number of people with selected variable).
                    Upon clicking the `Plot Demographic Data` button, you can view the interactive heatmap of your selected variable in your catchment area, and assess the distribution
                    plot below which shows the variable's distribution across all census tracts in your catchment area.
                    ''')
        st.markdown('''3. Overlaying Points-of-Interest: Finally, navigate to the `POI Overlay` tab to plot points of interest within your catchment area.
                    Select your POI categoy (e.g., cafes, fast food, dentist, car wash, etc.) and specify your map type (POI markers or heatmap). Upon clicking the
                    `Plot POI Data` button, you can view your points-of-interest within your catchment area using the interactive map.
                    ''')
        st.subheader('Open-Source Data APIs:')
        st.markdown('- [Nominatim](https://nominatim.org/): For geocoding addresses.')
        st.markdown('- [OpenStreetMap](https://wiki.openstreetmap.org/): For geographical data and POIs.')
        st.markdown('- [U.S. Census Bureau](https://www.census.gov/data/developers/data-sets.html): For demographic data (American Community Survey) and census-defined geometries (census tracts).')
        st.markdown('- [OpenRouteService](https://openrouteservice.org/): For calculating drive times.')
        st.caption("""Like this app? Check out what else we're up to at www.torainsights.ai""")
        
# Run app
if __name__ == "__main__":
    main()
