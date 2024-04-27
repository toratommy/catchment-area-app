# catchment_area.py
import geopandas as gpd
from shapely.geometry import shape, Point
from shapely.ops import transform
from functools import partial
import pyproj
from src.utils import load_state_boundaries, find_intersecting_states, calculate_overlapping_tracts, fetch_census_data_for_tracts, fetch_poi_within_catchment

class CatchmentArea:
    def __init__(self, location, radius_type, radius, travel_profile=None, ors_client=None):
        self.radius_type = radius_type
        self.radius = radius
        self.travel_profile = travel_profile
        self.location = location
        self.ors_client = ors_client
        self.geometry = None
        self.properties = None
        self.census_data = None
        self.census_tracts = None
        self.poi_data = None

    def geocode_address(self, address):
        try:
            return self.geolocator.geocode(address)
        except:
            return None

    def generate_geometry(self):
        if self.radius_type == 'Distance (miles)':
            return self.draw_circle()
        elif self.radius_type == 'Travel time (minutes)':
            return self.draw_drive_time_area()
        else:
            raise ValueError("Invalid radius type specified")

    def draw_circle(self):
        if not self.location:
            raise ValueError("Invalid location.")
        radius_meters = self.radius * 1609.34  # Convert miles to meters
        point = Point(self.location.longitude, self.location.latitude)
        # Transform to approximate on a spherical surface
        az_ea_proj = partial(
            pyproj.transform,
            pyproj.Proj(f'+proj=aeqd +lat_0={self.location.latitude} +lon_0={self.location.longitude} +x_0=0 +y_0=0'),
            pyproj.Proj('+proj=longlat +datum=WGS84')
        )
        circle_poly = transform(az_ea_proj, point.buffer(radius_meters))
        self.geometry = circle_poly
        return self.geometry

    def draw_drive_time_area(self):
        if not self.location or not self.ors_client:
            raise ValueError("Invalid location or OpenRouteService client not configured.")
        travel_profile_dict = {
            "Driving (car)": 'driving-car', "Driving (heavy goods vehicle)": 'driving-hgv', "Walking": 'foot-walking',
            "Cycling (regular)": 'cycling-regular', "Cycling (road)": 'cycling-road', "Cycling (mountain)": 'cycling-mountain',
            "Cycling (electric)": 'cycling-electric', "Hiking": 'foot-hiking', "Wheelchair": 'wheelchair'
        }
        coordinates = [[self.location.longitude, self.location.latitude]]
        params = {
            'locations': coordinates,
            'range': [self.radius * 60],  # Convert minutes to seconds
            'range_type': 'time',
            'profile': travel_profile_dict[self.travel_profile],
            'attributes': ['area', 'total_pop']
        }
        response_iso = self.ors_client.isochrones(**params)
        self.geometry = shape(response_iso['features'][0]['geometry'])
        self.iso_properties = response_iso['features'][0]['properties']
        return self.geometry
    
    def demographic_enrichment(self, census_api, acs_variables, acs_year, normalization):
        if not self.geometry:
            raise ValueError("Catchment area not defined.")
        states_gdf = load_state_boundaries(acs_year)
        catchment_gdf = gpd.GeoDataFrame(index=[0], crs='EPSG:4326', geometry=[self.geometry])
        intersecting_states = find_intersecting_states(catchment_gdf, states_gdf)
        overlapping_tracts = calculate_overlapping_tracts(catchment_gdf, intersecting_states, acs_year)

        # Fetch census data
        census_data = fetch_census_data_for_tracts(census_api, acs_year, acs_variables, overlapping_tracts, normalization)
        self.census_data = census_data
        self.census_tracts = overlapping_tracts
        return census_data, overlapping_tracts
    
    def poi_enrichment(self, categories):
        if not self.geometry:
            raise ValueError("Catchment area not defined.")
        poi_data = {}
        for category in categories:
            poi_data[category] = fetch_poi_within_catchment(self.geometry, category)
        self.poi_data = poi_data
        return poi_data