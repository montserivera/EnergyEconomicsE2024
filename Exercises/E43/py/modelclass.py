import os
curr = os.getcwd()
_repo = 'EnergyEconomicsE2024'
_repodir = os.path.join(os.getcwd().split(_repo,1)[0],_repo)
_pydir = os.path.join(_repodir,'py')
os.chdir(_pydir)
from base import *
# from baseSparse import *
from lpCompiler import _blocks
from lpModels import modelShell
os.chdir(curr)

# Functions for all technology types:
def fuelCost(db):
	return db['FuelPrice'].add(pyDbs.pdSum(db['EmissionIntensity'] * db['EmissionTax'], 'EmissionType'), fill_value=0)

def mc(db):
	""" Marginal costs in €/GJ """
	return pyDbs.pdSum((db['FuelMix'] * fuelCost(db)).dropna(), 'BFt').add(db['OtherMC'], fill_value=0)

def fuelConsumption(db):
	return pyDbs.pdSum((db['FuelMix'] * (adjMultiIndex.applyMult(subsetIdsTech(db['Generation_E'], ('standard_E','BP'), db), db['g_E2g']).droplevel('g_E').add(
										 adjMultiIndex.applyMult(subsetIdsTech(db['Generation_H'], 'standard_H', db), db['g_H2g']).droplevel('g_H'), fill_value = 0))).dropna(), ['h','id'])

def plantEmissionIntensity(db):
	return pyDbs.pdSum(db['FuelMix'] * db['EmissionIntensity'], 'BFt')

def emissionsFuel(db):
	return pyDbs.pdSum(fuelConsumption(db) * db['EmissionIntensity'], 'BFt')

def theoreticalCapacityFactor(db):
	return pyDbs.pdSum((subsetIdsTech(db['Generation_E'], ('standard_E','BP'), db) / pdNonZero(len(db['h']) * db['GeneratingCap_E'])).dropna(), 'h').droplevel('g_E')

def marginalSystemCosts(db,market):
	return -adj.rc_AdjPd(db[f'λ_equilibrium_{market}'], alias={'h_constr':'h', f'g_{market}_constr': f'g_{market}'}).droplevel('_type')

def meanMarginalSystemCost(db, var, market):
	return pyDbs.pdSum( (var * marginalSystemCosts(db,market)) / pdNonZero(pyDbs.pdSum(var, 'h')), 'h')

def marginalEconomicValue(m):
	""" Defines over id """
	return pd.Series.combine_first( subsetIdsTech(-pyDbs.pdSum((m.db['λ_Generation_E'].xs('u',level='_type')  * m.hourlyCapFactors).dropna(), 'h').add( 1000 * m.db['FOM'] * len(m.db['h'])/8760, fill_value = 0).droplevel('g_E'),('standard_E','BP'), m.db),
									subsetIdsTech(-pyDbs.pdSum((m.db['λ_Generation_H'].xs('u',level='_type')  * m.hourlyCapFactors).dropna(), 'h').add( 1000 * m.db['FOM'] * len(m.db['h'])/8760, fill_value = 0).droplevel('g_H'),('standard_H','HP'), m.db)
									)

def getTechs(techs, db):
	""" Subset on tech types"""
	return adj.rc_pd(db['id2modelTech2tech'].droplevel('tech'), pd.Index(techs if is_iterable(techs) else [techs], name = 'modelTech')).droplevel('modelTech')

def getTechs_i(techs, db):
	""" Subset on tech types"""
	return adj.rc_pd(db['id2modelTech2tech'].droplevel('modelTech'), pd.Index(techs if is_iterable(techs) else [techs], name = 'tech')).droplevel('tech')

def subsetIdsTech(x, techs, db):
	return adj.rc_pd(x, getTechs(techs,db))

def subsetIdsTech_i(x, techs, db):
	return adj.rc_pd(x, getTechs_i(techs,db))

class mSimple(modelShell):
	""" This class includes 
		(1) Electricity and heat markets, 
		(2) multiple geographic areas, 
		(3) trade in electricity, 
		(4) intermittency in generation, 
		(5) CHP plants and heat pumps """
	def __init__(self, db, blocks = None, **kwargs):
		db.updateAlias(alias=[(k, k+'_constr') for k in ('h','g_E','g_H','g','id')]+[(k, k+'_alias') for k in ['g_E']])
		db['gConnected'] = db['lineCapacity'].index
		db['id2modelTech2tech'] = sortAll(adjMultiIndex.bc(pd.Series(0, index = db['id2tech']), db['tech2modelTech'])).index
		super().__init__(db, blocks=blocks, **kwargs)

	def mapToG(self, symbol, market, alias = None):
		return adjMultiIndex.applyMult(symbol, adj.rc_pd(self.db[f'g_{market}2g'], alias = alias))

	@property
	def modelTech_E(self):
		return ('standard_E','BP','HP')
	@property
	def modelTech_H(self):
		return ('standard_H','BP','HP')
	@property
	def hourlyCapFactors(self):
		return adjMultiIndex.bc(self.db['CapVariation'], self.db['id2hvt']).droplevel('hvt')
	@property
	def hourlyGeneratingCap_E(self):
		return subsetIdsTech( (adjMultiIndex.bc(self.db['GeneratingCap_E'], self.db['id2hvt']) * self.db['CapVariation']).dropna().droplevel('hvt'),
								('standard_E','BP'), self.db)
	@property
	def hourlyGeneratingCap_H(self):
		return subsetIdsTech( (adjMultiIndex.bc(self.db['GeneratingCap_H'], self.db['id2hvt']) * self.db['CapVariation']).dropna().droplevel('hvt'),
								('standard_H','HP'), self.db)
	@property
	def hourlyTransmissionCap_E(self):
		(self.db['lineVariation'] * self.db['lineCapacity']).reorder_levels(['g_E','g_E_alias','h'])
	@property
	def hourlyLoad_cE(self):
		return adjMultiIndex.bc(self.db['Load_E'] * self.db['LoadVariation_E'], self.db['c_E2g_E']).reorder_levels(['c_E','g_E','h'])
	@property
	def hourlyLoad_cH(self):
		return adjMultiIndex.bc(self.db['Load_H'] * self.db['LoadVariation_H'], self.db['c_H2g_H']).reorder_levels(['c_H','g_H','h'])
	@property
	def hourlyLoad_E(self):
		return pyDbs.pdSum(self.hourlyLoad_cE, 'c_E')
	@property
	def hourlyLoad_H(self):
		return pyDbs.pdSum(self.hourlyLoad_cH, 'c_H')

	def preSolve(self, recomputeMC=False, **kwargs):
			if ('mc' not in self.db.symbols) or recomputeMC:
				self.db['mc'] = mc(self.db)

	@property
	def globalDomains(self):
		return {'Generation_E': pyDbs.cartesianProductIndex([subsetIdsTech(self.db['id2g_E'], self.modelTech_E, self.db), self.db['h']]),
				'Generation_H': pyDbs.cartesianProductIndex([subsetIdsTech(self.db['id2g_H'], self.modelTech_H, self.db), self.db['h']]),
				'HourlyDemand_E': pyDbs.cartesianProductIndex([self.db['c_E2g_E'], self.db['h']]),
				'HourlyDemand_H': pyDbs.cartesianProductIndex([self.db['c_H2g_H'], self.db['h']]),
				'Transmission_E': pyDbs.cartesianProductIndex([self.db['gConnected'],self.db['h']]),
				'equilibrium_E': pd.MultiIndex.from_product([self.db['g_E_constr'], self.db['h_constr']]),
				'equilibrium_H': pd.MultiIndex.from_product([self.db['g_H_constr'], self.db['h_constr']]),
				'PowerToHeat': pyDbs.cartesianProductIndex([adj.rc_AdjPd(getTechs(['BP','HP'],self.db), alias = {'id':'id_constr'}), self.db['h_constr']])}

	def initBlocks(self, **kwargs):
		[getattr(self.blocks, f'add_{t}')(**v) for t in _blocks if hasattr(self,t) for v in getattr(self,t)];

	@property
	def c(self):
		return [{'varName': 'Generation_E', 'value': adjMultiIndex.bc(self.db['mc'], self.globalDomains['Generation_E']).reorder_levels(self.globalDomains['Generation_E'].names), 'conditions': getTechs(['standard_E','BP'],self.db)},
				{'varName': 'Generation_H', 'value': adjMultiIndex.bc(self.db['mc'], self.globalDomains['Generation_H']).reorder_levels(self.globalDomains['Generation_H'].names), 'conditions': getTechs(['standard_H','HP'],self.db)},
				{'varName': 'HourlyDemand_E','value':-adjMultiIndex.bc(self.db['MWP_E'], self.globalDomains['HourlyDemand_E']).reorder_levels(self.globalDomains['HourlyDemand_E'].names)},
				{'varName': 'HourlyDemand_H','value':-adjMultiIndex.bc(self.db['MWP_H'], self.globalDomains['HourlyDemand_H']).reorder_levels(self.globalDomains['HourlyDemand_H'].names)},
				{'varName': 'Transmission_E','value': adjMultiIndex.bc(self.db['lineMC'], self.globalDomains['Transmission_E'])}]
	@property
	def u(self):
		return [{'varName': 'Generation_E', 'value': adjMultiIndex.bc(self.hourlyGeneratingCap_E, self.globalDomains['Generation_E']).reorder_levels(self.globalDomains['Generation_E'].names), 'conditions': getTechs(['standard_E','BP'],self.db)},
				{'varName': 'Generation_H', 'value': adjMultiIndex.bc(self.hourlyGeneratingCap_H, self.globalDomains['Generation_H']).reorder_levels(self.globalDomains['Generation_H'].names), 'conditions': getTechs(['standard_H','HP'],self.db)},
				{'varName': 'HourlyDemand_E','value':self.hourlyLoad_cE},
				{'varName': 'HourlyDemand_H','value':self.hourlyLoad_cH},
				{'varName': 'Transmission_E', 'value': adjMultiIndex.bc(self.hourlyTransmissionCap_E, self.globalDomains['Transmission_E'])}]
	@property
	def l(self):
		return [{'varName': 'Generation_E', 'value': -np.inf, 'conditions': getTechs('HP',self.db)}]
	@property
	def b_eq(self):
		return [{'constrName': 'PowerToHeat'}]
	@property
	def A_eq(self):
		return [{'constrName': 'PowerToHeat', 'varName': 'Generation_E', 'value': appIndexWithCopySeries(pd.Series(1, index = self.globalDomains['Generation_E']), ['id','h'], ['id_constr','h_constr']), 'conditions': getTechs(['BP','HP'],self.db)},
				{'constrName': 'PowerToHeat', 'varName': 'Generation_H', 'value': appIndexWithCopySeries(adjMultiIndex.bc(-self.db['E2H'], self.globalDomains['Generation_H']), ['id','h'],['id_constr','h_constr']), 'conditions': getTechs(['BP','HP'],self.db)}]
	@property
	def b_ub(self):
		return [{'constrName': 'equilibrium_E'}, {'constrName': 'equilibrium_H'}]
	@property
	def A_ub(self):
		return [{'constrName': 'equilibrium_E', 'varName': 'Generation_E', 'value': appIndexWithCopySeries(pd.Series(-1, index = self.globalDomains['Generation_E']), ['g_E','h'],['g_E_constr','h_constr'])},
				{'constrName': 'equilibrium_E', 'varName': 'HourlyDemand_E','value':appIndexWithCopySeries(pd.Series(1, index = self.globalDomains['HourlyDemand_E']), ['g_E','h'],['g_E_constr','h_constr'])},
				{'constrName': 'equilibrium_E', 'varName': 'Transmission_E','value': [appIndexWithCopySeries(pd.Series(1, index = self.globalDomains['Transmission_E']), ['g_E','h'],['g_E_constr','h_constr']),
																					  appIndexWithCopySeries(pd.Series(self.db['lineLoss']-1, index = self.globalDomains['Transmission_E']), ['g_E_alias','h'], ['g_E_constr','h_constr'])]},
				{'constrName': 'equilibrium_H', 'varName': 'Generation_H', 'value': appIndexWithCopySeries(pd.Series(-1, index = self.globalDomains['Generation_H']), ['g_H','h'],['g_H_constr','h_constr'])},
				{'constrName': 'equilibrium_H', 'varName': 'HourlyDemand_H','value':appIndexWithCopySeries(pd.Series(1, index = self.globalDomains['HourlyDemand_H']), ['g_H','h'],['g_H_constr','h_constr'])}]

	def postSolve(self, solution, **kwargs):
		if solution['status'] == 0:
			self.unloadToDb(solution)
			self.db['Welfare'] = -solution['fun']
			self.db['FuelConsumption'] = fuelConsumption(self.db)
			self.db['Emissions'] = emissionsFuel(self.db)
			self.db['marginalSystemCosts_E'] = marginalSystemCosts(self.db, 'E')
			self.db['marginalSystemCosts_H'] = marginalSystemCosts(self.db, 'H')
			self.db['marginalEconomicValue'] = marginalEconomicValue(self)
			self.db['meanConsumerPrice_E'] = meanMarginalSystemCost(self.db, self.db['HourlyDemand_E'],'E')
			self.db['meanConsumerPrice_H'] = meanMarginalSystemCost(self.db, self.db['HourlyDemand_H'],'H')