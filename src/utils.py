import streamlit as st
import folium
from geopy.geocoders import Nominatim
import pandas as pd
import requests
import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.ops import transform
import pyproj
from functools import partial
from census import Census
from scipy import *
import plotly.figure_factory as ff
import osmnx as ox
from folium.plugins import HeatMap
from folium.raster_layers import WmsTileLayer
from folium.raster_layers import TileLayer
from shapely.geometry import mapping
from folium.plugins import Fullscreen

def update_map_layer(session_state):
    # Update the tile layer based on user selection without resetting the existing overlays
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(session_state.catchment_map)
        if "bounds" in session_state:
            session_state.catchment_map.fit_bounds(st.session_state.bounds)
    else:
        session_state.catchment_map = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)
        if "bounds" in session_state:
            session_state.catchment_map.fit_bounds(st.session_state.bounds)


def map_tile_layer_selections():
    tile_layer_dict = {"OpenStreetMap":"OpenStreetMap",
                       "CartoDB Positron":"CartoDB Positron", 
                       "CartoDB Voyager":"CartoDB Voyager", 
                       "CartoDB Dark Matter":"CartoDB Dark Matter", 
                       "ESRI Imagery":WmsTileLayer(url='http://services.arcgisonline.com/arcgis/rest/services/World_Imagery'+ '/MapServer/tile/{z}/{y}/{x}',
                                                   layers=None,
                                                   name='ESRI Imagery',
                                                   attr='ESRI World Imagery')
    }
    tile_layer_input = st.selectbox("Select Map Layer", 
                                    list(tile_layer_dict.keys()), 
                                    index=0)
    tile_layer_value = tile_layer_dict[tile_layer_input]
    if tile_layer_input == tile_layer_value:
        tile_layer_type = 'Base'
    else:
        tile_layer_type = 'WMS'
    return tile_layer_value, tile_layer_type

@st.experimental_fragment
def make_catchment_area_selections():
    """
    Display widgets to collect user inputs for generating a catchment area.

    Returns
    -------
    tuple
        A tuple containing the entered address as a string, the selected radius type as a string,
        and the specified radius as an integer.
    """
    address = st.text_input("Enter the Address", 
                            value='1 N Halsted St, Chicago, IL 60661')
    radius_type = st.selectbox("Enter Radius Type", 
                               ["Distance (miles)", "Travel time (minutes)"], 
                               index = 1)
    if radius_type ==  'Travel time (minutes)':
        travel_profile = st.selectbox("Select Travel Profile",
                                      ["Driving (car)","Driving (heavy goods vehicle)","Walking","Cycling (regular)","Cycling (road)","Cycling (mountain)","Cycling (electric)","Hiking","Wheelchair"])
        max_radius = 60
    else:
        travel_profile = None
        max_radius = 250
    radius = st.number_input(f"Enter Radius {radius_type.split()[-1]}", 
                             min_value=1, 
                             max_value=max_radius, 
                             value=10,
                             help="The max supported travel time radius is 60 minutes. Please set radius type to `Distance (miles)` if you wish to generate a larger area.")
    return address, radius_type, travel_profile, radius

@st.experimental_fragment
def make_census_variable_selections(filters_dict):
    """
    Display widgets to select demographic variables for data enrichment.

    Parameters
    ----------
    filters_dict : dict
        A dictionary with demographic variable groups as keys and lists of variable names as values.

    Returns
    -------
    tuple
        A tuple containing the selected variable group as a string, the selected variable name as a string,
        and the normalization preference as a string.
    """
    var_group = st.selectbox('Choose Census Variable Group', options=(v for v in filters_dict.keys()),index=445)
    var_name = st.selectbox('Choose Census Variable Name', options=filters_dict[var_group])
    normalization = st.radio("Normalize by Population?",["No", "Yes"],index=0)
    return var_group, var_name, normalization

@st.experimental_fragment
def make_poi_selections(amenity_list):
    """
    Display widgets for selecting POI categories and mapping preferences.

    Parameters
    ----------
    amenity_list : list
        A list of POI categories to choose from.

    Returns
    -------
    tuple
        A tuple containing the list of selected POI categories as a list of strings, and the chosen map type as a string.
    """
    poi_categories = st.multiselect('Select POI categories to map',amenity_list)
    poi_map_type = st.radio('Choose map type:', ['POI markers','Heatmap (POI density)'])
    return poi_categories, poi_map_type

def geocode_address(address):
    """
    Geocodes an address to a latitude and longitude.
    
    Parameters
    ----------
    address : str
        The address to geocode.
    
    Returns
    -------
    geopy.location.Location or None
        The location object for the address or None if geocoding fails.
    """
    geolocator = Nominatim(user_agent="catchment_area_explorer")
    try:
        return geolocator.geocode(address)
    except:
        return None

def plot_catchment_area(session_state):
    """
    plots an area based on drive time from a specified location.
    
    Parameters
    ----------
    catchment_map : folium.Map
        The map on which to plot the drive time area.
    location : geopy.location.Location
        The central point from which to calculate drive time area.
    drive_time : int
        The drive time in minutes.
    client : openrouteservice.Client
        The client to use for OpenRouteService API requests.
    
    Returns
    -------
    shapely.geometry.Polygon
        The polygon representing the drive time area.
    """

    polygon = folium.GeoJson(session_state.catchment_area.geometry, style_function=lambda x:{'fillColor': 'blue', 'color': 'blue'})
    polygon.add_to(st.session_state.catchment_map)

    bounds = polygon.get_bounds()
    st.session_state.catchment_map.fit_bounds(bounds)

@st.cache_data    
def fetch_census_variables(api_url):
    """
    Fetches census variables from the U.S. Census API.
    
    Parameters
    ----------
    api_url : str
        The base URL for the Census API endpoint.
    
    Returns
    -------
    pandas.DataFrame or None
        A DataFrame containing the census variables and metadata, or None if the fetch fails.
    """
    variables_url = f"{api_url}/variables.json"
    try:
        response = requests.get(variables_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        variables_dict = response.json()
        variables_df = pd.concat({k: pd.DataFrame(v).T for k, v in variables_dict.items()}, axis=0)
        variables_df = variables_df[variables_df['label'].str.contains('Estimate')].reset_index()
        variables_df.rename(columns={'level_1':'variable','concept':'Variable Group','label':'Variable Name'}, inplace=True)
        variables_df['Variable Name'] = variables_df['Variable Name'].str.replace('Estimate!!', '').str.replace('!!', ' ')
        return variables_df
    except requests.RequestException as e:
        print(f"Failed to fetch variables.json: {e}")
        return None
    
@st.cache_data    
def load_state_boundaries(census_year):
    """
    Loads state boundaries using the US Census Bureau's cartographic boundary files for a given year.
    
    Parameters
    ----------
    census_year : str
        The census year for which to load state boundaries.
    
    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame containing the state boundaries.
    """
    url = "https://www2.census.gov/geo/tiger/GENZ{0}/shp/cb_{0}_us_state_20m.zip".format(census_year)
    gdf = gpd.read_file(url)
    return gdf

def find_intersecting_states(user_gdf, states_gdf):
    """
    Identifies states that intersect with a user-defined geography.
    
    Parameters
    ----------
    user_gdf : geopandas.GeoDataFrame
        The user-defined geography.
    states_gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing state boundaries.
    
    Returns
    -------
    pandas.Series
        The GEOID of states that intersect with the user-defined geography.
    """
    intersecting_states = states_gdf[states_gdf.intersects(user_gdf.unary_union)]
    return intersecting_states['GEOID']

@st.cache_data
def load_tract_shapefile(state_code, census_year):
    """
    Loads a census tract shapefile from the Census website for a given state code and year.
    
    Parameters
    ----------
    state_code : str
        The state code for which to load the census tract shapefile.
    census_year : str
        The year of the census.
    
    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame containing the census tract shapefile data.
    """
    url = f"https://www2.census.gov/geo/tiger/TIGER{census_year}/TRACT/tl_{census_year}_{state_code}_tract.zip"
    gdf = gpd.read_file(url)
    return gdf

def calculate_overlapping_tracts(user_gdf, state_codes, census_year):
    """
    Calculates which tracts overlap with the user-defined geography for intersecting states.
    
    Parameters
    ----------
    user_gdf : geopandas.GeoDataFrame
        The user-defined geography.
    state_codes : list of str
        The state codes of the intersecting states.
    census_year : str
        The year of the census data.
    
    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame of overlapping tracts.
    """
    overlapping_tracts = gpd.GeoDataFrame()
    for state_code in state_codes:
        tract_gdf = load_tract_shapefile(state_code, census_year)
        
        # Calculate the intersection area between each tract and the user-defined geography
        tract_gdf['intersection_area'] = tract_gdf.geometry.apply(lambda x: x.intersection(user_gdf.unary_union).area)
        
        # Calculate the percentage of each tract covered by the user-defined geography
        tract_gdf['coverage_percentage'] = (tract_gdf['intersection_area'] / tract_gdf.geometry.area) * 100
        
        # Filter tracts where the coverage percentage is greater than 30%
        tracts_overlapping = tract_gdf[tract_gdf['coverage_percentage'] > 30]
        
        overlapping_tracts = pd.concat([overlapping_tracts, tracts_overlapping])

    # Drop the temporary columns used for calculations
    overlapping_tracts = overlapping_tracts.drop(columns=['intersection_area', 'coverage_percentage'])

    return overlapping_tracts

def fetch_census_data_for_tracts(census_api, census_year, variables, overlapping_tracts, normalization):
    """
    Fetches census data for tracts within overlapping tracts dataframe.
    
    Parameters
    ----------
    census_api : census.Census
        The Census API client.
    census_year : str
        The year of the census.
    variables : list of str
        The list of variables to fetch.
    overlapping_tracts : geopandas.GeoDataFrame
        The GeoDataFrame of overlapping tracts.
    normalization : str
        Indicates if the data should be normalized.
    
    Returns
    -------
    pandas.DataFrame
        A DataFrame containing the fetched census data.
    """
    # Prepare an empty DataFrame to hold fetched census data
    all_census_data = pd.DataFrame()

    # Group the overlapping tracts by state and county for batch fetching
    for (state_code, county_code), group in overlapping_tracts.groupby(['STATEFP', 'COUNTYFP']):
        # Fetch census data for all tracts within this state and county
        if normalization == 'Yes':
            fetch_vars = variables+['B01003_001E']
        else:
            fetch_vars = variables
        
        tracts_data = census_api.acs5.state_county_tract(fetch_vars, state_code, county_code, Census.ALL, year=census_year)
        # Convert the fetched data into a DataFrame
        tracts_df = pd.DataFrame(tracts_data)
        
        # Convert GEOID to a format that matches the overlapping_tracts for comparison
        tracts_df['GEOID'] = tracts_df.apply(lambda row: f"{row['state']}{row['county']}{row['tract']}", axis=1)
        
        # Filter the data to only include those tracts that are in the overlapping_tracts DataFrame
        tracts_df = tracts_df[tracts_df['GEOID'].isin(overlapping_tracts['GEOID'])]
        
        # Append the filtered data to the all_census_data DataFrame
        all_census_data = pd.concat([all_census_data, tracts_df], ignore_index=True)
        if normalization == 'Yes':
            all_census_data['population_normalized'] = all_census_data[variables[0]]/all_census_data['B01003_001E']

    return all_census_data

def plot_census_data_on_map(session_state, overlapping_tracts_gdf, census_data, census_variable, var_name, normalization):
    """
    Plots census data on a map, coloring tracts by a specified census variable.
    
    Parameters
    ----------
    session_state : st.session_state
        The current session state data.
    overlapping_tracts_gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing the geometries of the tracts.
    census_data : pandas.DataFrame
        The DataFrame containing the census data for the tracts.
    census_variable : str
        The census variable to color the tracts by.
    var_name : str
        The name of the variable (for display purposes).
    normalization : str
        Indicates if the data should be normalized.
    
    Returns
    -------
    None
    """
    # Initialize Census Map using user-selected map layer
    map_center = [session_state.catchment_area.centroid.y, session_state.catchment_area.centroid.x]
    m = folium.Map(location=map_center, tiles=None)
    # Handle both regular and WMS tile layers
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(m)
    else:
        m = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)

    Fullscreen(position="topright", title="Expand me", title_cancel="Exit me", force_separate_button=True).add_to(m)
    # Existing code for merging data and adding GeoJson layer
    merged_data = overlapping_tracts_gdf.merge(census_data, left_on='GEOID', right_on='GEOID')
    geojson_data = merged_data.to_json()

    if normalization == 'Yes':
        plot_var = 'population_normalized'
        alias = var_name+' (Population Normalized):'
        deciles = merged_data['population_normalized'].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()
    else:
        plot_var = census_variable
        alias = var_name+':'
        deciles = merged_data[census_variable].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()

    folium.GeoJson(
        geojson_data,
        style_function=lambda feature: {
            'fillColor': get_color(feature['properties'][plot_var], deciles),
            'color': 'black',
            'weight': 0.1,
            'fillOpacity': 0.7,
        },
        tooltip=folium.GeoJsonTooltip(fields=[plot_var],
                                      aliases=[alias],
                                      localize=True)
    ).add_to(m)
    m.fit_bounds(session_state.bounds)
    return m

    
def get_color(value, deciles):
    """
    Determines the color for a value based on which decile it falls into.
    
    Parameters
    ----------
    value : float
       The value to be colored.
    deciles : list of float
        The decile thresholds for coloring.
    
    Returns
    -------
    str
        The color code for the given value based on its decile.
    """
    colors = ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c',
              '#fc4e2a', '#e31a1c', '#bd0026', '#800026', '#66001a']
    
    if value is None:
        return '#999999'  # Default color for missing values
    for i, threshold in enumerate(deciles):
        if value <= threshold:
            return colors[i]
    return colors[-1]  # Use the last color for values in the highest decile

def calculate_area_sq_miles(catchment_area):
    """
    Calculates the area of a user-defined polygon in square miles.

    Parameters
    ----------
    catchment_area : shapely.geometry.Polygon
        A polygon in latitude and longitude coordinates.

    Returns
    -------
    float
        The area of the polygon in square miles.
    """
    proj = partial(pyproj.transform,
                   pyproj.Proj(init='epsg:4326'),  # Source coordinate system (WGS84)
                   pyproj.Proj(proj='aea', lat_1=catchment_area.bounds[1], lat_2=catchment_area.bounds[3]))  # Albers Equal Area projection
    projected_polygon = transform(proj, catchment_area) 
     # Project the polygon to the new coordinate system
    area_sq_miles = round(projected_polygon.area / 2589988.11,2)  # Convert area from square meters to square miles
    return area_sq_miles

def create_distribution_plot(census_data, variables, var_name, normalization):
    """
    Creates a distribution plot for a specified census variable.

    Parameters
    ----------
    census_data : pandas.DataFrame
        The census data containing variables of interest.
    variables : list of str
        The census variables to include in the plot.
    var_name : str
        The name of the variable to be plotted.
    normalization : str
        Indicates whether the data should be normalized.

    Returns
    -------
    plotly.graph_objs.Figure
        The figure object containing the distribution plot.
    """
    # Create distplot with custom bin_size
    if normalization == 'Yes':
        dist_data = census_data[census_data[variables[0]]>0]['population_normalized']
        label = var_name+' (Population Normalized)'
    else:
        dist_data = census_data[census_data[variables[0]]>0][variables[0]]
        label = var_name
    fig = ff.create_distplot([dist_data], group_labels = [label])
    fig.update_layout(legend=dict(orientation="h",
                                    yanchor="bottom",
                                    y=1.02,
                                    xanchor="right",
                                    x=1
                                    )
    )
    return fig

def fetch_poi_within_catchment(catchment_polygon, category):
    """
    Fetch points of interest within a specified catchment area polygon and category.

    Parameters
    ----------
    catchment_polygon: 
        A Shapely Polygon defining the catchment area.
    category: 
        A string representing the OSM category of interest (e.g., 'cafe', 'restaurant').

    Returns:
    -------
    GeoDataFrame()
        GeoDataFrame containing the fetched POI data.
    """
    try:
        # Define the tags for OSM queries based on the specified category
        tags = {'amenity': category}
        
        # Attempt to fetch POIs within the catchment area polygon
        pois_gdf = ox.features_from_polygon(catchment_polygon, tags=tags)
        
        # Check if the returned GeoDataFrame is empty
        if pois_gdf.empty:
            print("No data returned for the specified category within the catchment area.")
            return gpd.GeoDataFrame()  # Return an empty GeoDataFrame
        
        return pois_gdf
    except Exception as e:
        print(f"An error occurred while fetching POIs: {e}")
        return gpd.GeoDataFrame()  
    
def plot_poi_data_on_map(pois_gdf, session_state, map_type):
    """
    Plots POI data on a map, either as markers or a heatmap, based on the specified map type.
    
    Parameters
    ----------
    pois_gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing POI data.
    catchment_polygon : shapely.geometry.Polygon
        The polygon defining the catchment area.
    map_type : str
        The type of map to plot ('POI markers' or 'Heatmap (POI density)').
    
    Returns
    -------
    folium.Map
        The map with POI data plotted.
    """
    # Create a map centered around the catchment area using the user-selected map layer
    map_center = [session_state.catchment_area.centroid.y, session_state.catchment_area.centroid.x]
    m = folium.Map(location=map_center, tiles=None, zoom_start=13)
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(m)
    else:
        m = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)

    Fullscreen(position="topright", title="Expand me", title_cancel="Exit me", force_separate_button=True).add_to(m)
    folium.GeoJson(mapping(session_state.catchment_area), style_function=lambda x: {'color': 'blue', 'fill': False}).add_to(m)
    
    if map_type == 'Heatmap (POI density)':
        heatmap_points = []
    
    for _, poi in pois_gdf.iterrows():
        poi_location = poi.geometry.centroid.coords[0]
        if map_type == 'POI markers':
            folium.Marker(location=[poi_location[1], 
                                    poi_location[0]], 
                                    popup=f"{poi.get('name', 'Unnamed')} - {', '.join(filter(None, [str(poi.get(field, '')) for field in ['addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode']]))}").add_to(m)
        elif map_type == 'Heatmap (POI density)':
            heatmap_points.append([poi_location[1], poi_location[0]])

    if map_type == 'Heatmap (POI density)':
        HeatMap(heatmap_points).add_to(m)

    return m

def display_poi_counts(pois_gdf):
    """
    Displays the total counts of POI locations by category.
    
    Parameters
    ----------
    pois_gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing POI data.
    
    Returns
    -------
    None
    """
    # Assuming 'amenity' column stores the POI category
    if not pois_gdf.empty and 'amenity' in pois_gdf.columns:
        counts = pois_gdf['amenity'].value_counts()
        for category, count in counts.items():
            st.write(f"`{category}`: {count} distinct locations")
            #st.dataframe(pois_gdf[['amenity','name','addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode']])
    else:
        st.write("No POI data available.")