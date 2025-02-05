import numpy as np
import pandas as pd
import quantipy as qp
import copy
import re
import warnings

from quantipy.core.tools.dp.query import uniquify_list
from quantipy.core.helpers.functions import (
    emulate_meta,
    cpickle_copy,
    get_rules_slicer,
    get_rules,
    paint_dataframe
)

from quantipy.core.tools.view.logic import (
    has_any,
    get_logic_index,
    intersection
)

from quantipy.core.rules import Rules

def recode_into(data, col_from, col_to, assignment, multi=False):
    ''' Recodes one column based on the values of another column
    codes = [([10, 11], 1), ([8, 9], 2), ([1, 2, 3, 5, 6, 7, ], 3)]
    data = recode_into(data, 'CONNECTIONS4', 'CONNECTIONS4_nps', codes)
    '''

    s = pd.Series()
    for group in assignment:
        for val in group[0]:
            data[col_to] = np.where(data[col_from] == val, group[1], np.NaN)
            s = s.append(data[col_to].dropna())
    data[col_to] = s
    return data

def create_column(name, type_name, text='', values=None):
    ''' Returns a column object that can be stored into a Quantipy meta
    document.
    '''

    column = {
        'name': name,
        'type': type_name,
        'text': text
    }

    if not values is None:
        column['values'] = values

    return column

def define_multicodes(varlist, meta):
    multicodes = {}
    for var in varlist:
        multicodes.update({var: [mrs_q for mrs_q in meta['columns'] if mrs_q.startswith(var + '_')]})

    return multicodes

def dichotomous_from_delimited(ds, value_map=None, sep=';', trailing_sep=True,
                               dichotom=[1, 2]):
    ''' Returns a dichotomous set DataFrame from ds, being a series storing
    delimited set data separated by 'sep'

    ds - (pandas.Series) a series storing delimited set data
    value_map - (list-like, optional)  the values to be anticipated as unique
        in ds
    sep - (str, optional) the character/s to use to delimit ds
    trailing_sep - (bool, optional) is sep trailing all items in ds?
    dichotom - (list-like, optional) the dochotomous values to use [yes, no]
    '''

    ds_split = ds.dropna().str.split(';')

    if value_map is None:
        value_map = get_delimited_value_map(ds, ds_split, sep)

    df = pd.DataFrame(data=dichotom[1], index=ds.index, columns=value_map)

    for idx in ds_split.index:
        if trailing_sep:
            cols = ds_split.loc[idx][:-1]
        else:
            cols = ds_split.loc[idx][:]
        df.loc[idx][cols] = dichotom[0]

    return df

def get_delimited_value_map(ds, ds_split=None, sep=';'):
    ''' Returns a sorted list of unique values found in ds, being a series
    storing delimited set data separated by sep

    ds - (pandas.Series) a series storing delimited set data
    ds_split - (pandas.DataFrame, optional) an Excel-style text-to-columns
        version of ds
    sep - (str, optional) the character/s to use to delimit ds
    '''

    if ds_split is None:
        ds_split = ds.dropna().str.split(sep)

    delimited = pd.DataFrame(ds_split.tolist())
    value_map = pd.unique(delimited.values.ravel())
    value_map = np.sort(value_map[value_map.nonzero()])

    return value_map

def derotate_column_group(data, cols, rotation_name='rotation',
                          data_name='data', dropna=True,
                          rotation_map=None):
    ''' Stacks the given columns from data, optionally renaming the
    resultiong rotation and data columns, mapping the values found in
    the rotation column, and appending the rotation column onto the index.

    Parameters
    ----------
    data : pandas.DataFrame
        The data from which the hierarchical groups are being drawn.

    cols : list
        A list column names that need to be stacked from the source
        data.

    rotation_name : str
        The name to be given to the rotation series that results from
        the pandas.DataFrame.stack() operation.

    data_name : str
        The name to be given to the data series that results from
        the pandas.DataFrame.stack() operation.

    dropna: boolean (optional; default=True)
        Passed through to the pandas.DataFrame.stack() operation.

    rotation_map: list (optional; default=None)
        The list of values/labels used to identify each resulting
        stacked row. Using a mapper allows multi-question hierarchies
        to be merged together because the resulting MultiIndexes will
        match.
    '''

    # For multi-level hierarchies, capture the new level number about
    # to be added|
    if isinstance(data.index, pd.MultiIndex):
        new_level = len(data.index.levels)
    else:
        new_level = 1

    df = data[cols].stack(dropna=dropna).reset_index(level=[new_level])
    df.columns = [rotation_name, data_name]

    if not rotation_map is None:
        df[rotation_name] = df[rotation_name].map(rotation_map)

    df.set_index([rotation_name], append=True, drop=True, inplace=True)

    return df


def derotate(data, input_mapper, output_mapper, others=None, dropna=True):
    """
    Derotate data using the given input_mapper, and appending others.

    This function derotates data using the specification defined in
    input_mapper, which is a list of dicts of lists, describing how
    columns from data can be read as a heirarchical structure.

    Parameters
    ----------
    data : pandas.DataFrame
        The data from which the hierarchical groups are being drawn.

    input_mapper : list of dicts of lists
        A list of dicts matching where the new column names are keys to
        to lists of source columns.

    output_mapper : dict
        The name and values to be given to the rotation index in the
        output dataframe.

    others: list (optional; default=None)
        A list of additional columns from the source data to be appended
        to the end of the resulting stacked dataframe.

    dropna: boolean (optional; default=True)
        Passed through to the pandas.DataFrame.stack() operation.

    Returns
    ----------
    df : pandas.DataFrame
        The stacked dataframe.
    """

    # For multi-level hierarchies, capture the new level number about
    # to be added|
    if isinstance(data.index, pd.MultiIndex):
        new_level = len(data.index.levels)
    else:
        new_level = 1

    rotation_name = list(output_mapper.keys())[0]
    rotation_index = output_mapper[rotation_name]

    # Collect all of the stacked column groups into a list
    dfs = []
    for question_group in input_mapper:
        question_name = list(question_group.keys())[0]
        question_columns = list(question_group.values())[0]
        df = derotate_column_group(
            data=data,
            cols=question_columns,
            rotation_name=rotation_name,
            data_name=question_name,
            dropna=dropna,
            rotation_map=dict(list(zip(question_columns, rotation_index)))
        )
        dfs.append(df)

    # Join all of the stacked dataframes together
    df = pd.concat(dfs, axis=1)

    if not others is None:
        # Merge in additional columns from the source data
        df.reset_index(level=[new_level], inplace=True)
        df = df.join(data[others])
        df.set_index([rotation_name], append=True, drop=True, inplace=True)

    return df

def start_meta(text_key='main'):
    """
    Starts a new Quantipy meta document.

    Parameters
    ----------
    text_key : str, default='main'
        The default text key to be set into the new meta document.

    Returns
    -------
    meta : dict
        Quantipy meta object
    """

    meta = {
        'info': {
            'text': ''
        },
        'lib': {
            'default text': text_key,
            'values': {}
        },
        'columns': {},
        'masks': {},
        'sets': {
            'data file': {
                'text': {text_key: 'Variable order in source file'},
                'items': []
            }
        },
        'type': 'pandas.DataFrame'
    }

    return meta

def condense_dichotomous_set(df, values_from_labels=True, sniff_single=False,
                             yes=1, no=0, values_regex=None):
    """
    Condense the given dichotomous columns to a delimited set series.

    Parameters
    ----------
    df : pandas.DataFrame
        The column/s in the dichotomous set. This may be a single-column
        DataFrame, in which case a non-delimited set will be returned.
    values_from_labels : bool, default=True
        Should the values used for each response option be taken from
        the dichotomous column names using the rule name.split('_')[-1]?
        If not then the values will be sequential starting from 1.
    sniff_single : bool, default=False
        Should the returned series be given as dtype 'int' if the
        maximum number of responses for any row is 1?

    Returns
    -------
    series: pandas.series
        The converted series
    """

    # Anything not counted as yes or no should be treated as no
    df = df.applymap(lambda x: x if x in [yes, no] else no)
    # Convert to delimited set
    df_str = df.astype('str')
    for v, col in enumerate(df_str.columns, start=1):
        if values_from_labels:
            if values_regex is None:
                v = col.split('_')[-1]
            else:
                try:
                    v = str(int(re.match(values_regex, col).groups()[0]))
                except AttributeError:
                    raise AttributeError(
                        "Your values_regex may have failed to find a match"
                        " using re.match('{}', '{}')".format(
                            values_regex, col))
        else:
            v = str(v)
        # Convert to categorical set
        df_str[col].replace(
            {
                'nan': 'nan',
                '{}.0'.format(no): 'nan',
                '{}'.format(no): 'nan'
            },
            inplace=True
        )
        df_str[col].replace(
            {
                '{}'.format(yes): v,
                '{}.0'.format(yes): v
            },
            inplace=True
        )
    # Concatenate the rows
    series = df_str.apply(
        lambda x: ';'.join([
            v
            for v in x.tolist()
            if v != 'nan'
        ]),
        axis=1
    )

    # Add trailing delimiter
    series = series + ';'

    # Use NaNs to represent emtpy
    series.replace(
        {';': np.NaN},
        inplace=True
    )

    if df.dropna().size==0:
        # No responses are known, return filled with NaN
        return series

    if sniff_single and df.sum(axis=1).max()==1:
        # Convert to float
        series = series.str.replace(';','').astype('float')
        return series

    return series

def split_series(series, sep, columns=None):
    """
    Splits all the items of a series using the given delimiter.

    Splits each item in series using the given delimiter and returns
    a DataFrame (as per Excel text-to-columns). Optionally, you can
    pass in a list of column names that should be used to name the
    resulting columns.

    Parameters
    ----------
    series : pandas.Series
        The series that should be split.
    sep : str
        The separator that should be used to split the series.
    columns : list-list, default=None
        A list of names that should be set into the resulting DataFrame
        columns.

    Returns
    -------
    df : pandas.DataFrame
        Series, split by sep, returned as a DataFrame.
    """

    df = pd.DataFrame(series.astype('str').str.split(sep).tolist())
    if not columns is None:
        df.columns = columns
    return df

def frange(range_def, sep=','):
    """
    Return the full, unabbreviated list of ints suggested by range_def.

    This function takes a string of abbreviated ranges, possibly
    delimited by a comma (or some other character) and extrapolates
    its full, unabbreviated list of ints.

    Parameters
    ----------
    range_def : str
        The range string to be listed in full.
    sep : str, default=','
        The character that should be used to delimit discrete entries in
        range_def.

    Returns
    -------
    res : list
        The exploded list of ints indicated by range_def.
    """

    res = []
    for item in range_def.split(sep):
        if '-' in item:
            a, b = item.split('-')
            a, b = int(a), int(b)
            lo = min([a, b])
            hi = max([a, b])
            ints = list(range(lo, hi+1))
            if b <= a:
                ints = list(reversed(ints))
            res.extend(ints)
        else:
            res.append(int(item))
    return res

def frequency(meta, data, x=None, y=None, weight=None, rules=False, **kwargs):
    """
    Return a type-appropriate frequency of x.

    This function uses the given meta and data to create a
    type-appropriate frequency table of the named x variable.
    The result may be either counts or column percentages, weighted
    or unweighted.

    Parameters
    ----------
    meta : dict
        Quantipy meta document.
    data : pandas.DataFrame
        Data accompanying the given meta document.
    x : str, default=None
        The column of data for which a frequency should be generated
        on the x-axis.
    y : str, default=None
        The column of data for which a frequency should be generated
        on the y-axis.
    kwargs : kwargs
        All remaining keyword arguments will be passed along to the
        crosstab function.

    Returns
    -------
    f : pandas.DataFrame
        The frequency as a pandas DataFrame.
    """

    if x is None and y is None:
        raise ValueError(
            "You must provide a value for either x or y."
        )
    elif not x is None and not y is None:
        raise ValueError(
            "You may only provide a value for either x or y, and not"
            " both, when generating a frequency."
        )

    if rules and isinstance(rules, bool):
        rules = ['x', 'y']

    if x is None:
        x = '@'
        col = y
        if rules:
            rules_axis = 'y'
            transpose = True
            if not 'y' in rules:
                rules = False
    else:
        y = '@'
        col = x
        if rules:
            rules_axis = 'x'
            transpose = False
            if not 'x' in rules:
                rules = False
    if rules:
        try:
            if col in meta['columns']:
                rules = meta['columns'][col]['rules'][rules_axis]
            elif col in meta['masks']:
                rules = meta['masks'][col]['rules'][rules_axis]
        except:
            rules = False

        if not qp.OPTIONS['new_rules']:
            try:
                with_weight = rules['sortx']['with_weight']
            except:
                with_weight = weight
        else:
            with_weight = weight
    else:
        with_weight = weight

    f = crosstab(
        meta, data, x, y,
        weight=with_weight,
        rules=False,
        xtotal=False,
        **kwargs)

    if rules:
        if not qp.OPTIONS['new_rules']:
            if transpose:
                f = f.T
            rules_slicer = get_rules_slicer(f, rules)
            f = f.loc[rules_slicer]
            if transpose:
                f = f.T
        else:
            f = crosstab(
                meta, data, x, y,
                weight=with_weight,
                rules=True,
                xtotal=False,
                **kwargs)

    return f

def crosstab(meta, data, x, y, get='count', decimals=1, weight=None,
             show='values', rules=False, xtotal=False):
    """
    Return a type-appropriate crosstab of x and y.

    This function uses the given meta and data to create a
    type-appropriate cross-tabulation (pivot table) of the named x and y
    variables. The result may be either counts or column percentages,
    weighted or unweighted.

    Parameters
    ----------
    meta : dict
        Quantipy meta document.
    data : pandas.DataFrame
        Data accompanying the given meta document.
    x : str
        The variable that should be placed into the x-position.
    y : str
        The variable that should be placed into the y-position.
    get : str, default='count'
        Control the type of data that is returned. 'count' will return
        absolute counts and 'normalize' will return column percentages.
    decimals : int, default=1
        Control the number of decimals in the returned dataframe.
    weight : str, default=None
        The name of the weight variable that should be used on the data,
        if any.
    show : str, default='values'
        How the index and columns should be displayed. 'values' returns
        the raw value indexes. 'text' returns the text associated with
        each value, according to the text key
        meta['lib']['default text']. Any other str value is assumed to
        be a non-default text_key.
    rules : bool or list-like, default=False
        If True then all rules that are found will be applied. If
        list-like then rules with those keys will be applied.
    xtotal : bool, default=False
        If True, the first column of the returned dataframe will be the
        regular frequency of the x column.

    Returns
    -------
    df : pandas.DataFrame
        The crosstab as a pandas DataFrame.
    """
    stack = qp.Stack(name='ct', add_data={'ct': {'meta': meta, 'data': data}})
    stack.add_link(x=x, y=y)
    link = stack['ct']['no_filter'][x][y]
    q = qp.Quantity(link, weight=weight).count()
    weight_notation = '' if weight is None else weight
    if get=='count':
        df = q.result
        vk = 'x|f|:||{}|counts'.format(weight_notation)
    elif get=='normalize':
        df = q.normalize().result
        vk = 'x|f|:|y|{}|c%'.format(weight_notation)
    else:
        raise ValueError(
           "The value for 'get' was not recognized. Should be 'count' or "
           "'normalize'."
        )
    df = np.round(df, decimals=decimals)
    if rules and isinstance(rules, bool):
        rules = ['x', 'y']

    if rules:
        if qp.OPTIONS['new_rules']:
            # new rules application
            # ----------------------------------------------------------------
            view = qp.core.view.View(link, vk)
            view.dataframe = df
            link[vk] = view
            rulesobj = Rules(link, vk, axes=rules)
            rulesobj.apply()
            if rulesobj.x_rules and 'x' in rules:
                idx = rulesobj.rules_df().index
                if not 'All' in idx.get_level_values(1).tolist():
                    df_index =  [(link.x, 'All')] + idx.values.tolist()
                else:
                    df_index = idx.values.tolist()
                df = df.loc[df_index]
            if rulesobj.y_rules and 'y' in rules:
                idx = rulesobj.rules_df().columns
                if not 'All' in idx.get_level_values(1).tolist():
                    df_columns = [(link.y, 'All')] + idx.values.tolist()
                else:
                    df_columns = idx.values.tolist()
                df = df[df_columns]
        else:
            # OLD!
            # ================================================================
            rules_x = get_rules(meta, x, 'x')
            if not rules_x is None and 'x' in rules:
                fx = frequency(meta, data, x=x, weight=weight, rules=True)
                if q._get_type() == 'array':
                    df = df.T
                    df = df.loc[fx.index.values]
                    df = df.T
                else:
                    df = df.loc[fx.index.values]
            rules_y = get_rules(meta, y, 'y')
            if not rules_y is None and 'y' in rules:
                fy = frequency(meta, data, y=y, weight=weight, rules=True)
                df = df[fy.columns.values]

    if show!='values':
        if show=='text':
            text_key = meta['lib']['default text']
        else:
            text_key = show
        if not isinstance(text_key, dict):
            text_key = {'x': text_key, 'y': text_key}
        df = paint_dataframe(meta, df, text_key)

    if xtotal:
        try:
            f = frequency(
                meta, data, x,
                get=get, decimals=decimals, weight=weight, show=show)
            f = f.loc[df.index.values]
        except:
            pass
        df = pd.concat([f, df], axis=1)

    if q._get_type() == 'array':
        df = df.T

    return df

def verify_test_results(df):
    """
    Verify tests results in df are consistent with existing columns.

    This function verifies that all of the test results present in df
    only refer to column headings that actually exist in df. This is
    needed after rules have been applied at which time some columns
    may have been dropped.

    Parameters
    ----------
    df : pandas.DataFrame
        The view dataframe showing column tests results.

    Returns
    -------
    df : pandas.DataFrame
        The view dataframe showing edited column tests results.
    """

    def verify_test_value(value):
        """
        Verify a specific test value.
        """
        if isinstance(value, str):
            is_minimum = False
            is_small = False
            if value.endswith('*'):
                if value.endswith('**'):
                    is_minimum = True
                    value = value[:-2]
                else:
                    is_small = True
                    value = value[:-1]
            if '@' in value:
                test_total = value[1:5]
                if len(value) <= 6:
                    if is_minimum:
                        value = value + '**'
                    elif is_small:
                        value = value + '*'
                    return value
                else:
                    value = value.replace(test_total, '').replace('[, ', '[')
            else:
                test_total = None
            if len(value)>0:
                if len(value)==1:
                    value = set(value)
                else:
                    value = set([int(i) for i in list(value[1:-1].split(','))])
                value = cols.intersection(value)
                if not value:
                    value = ''
                elif len(value)==1:
                    value = str(list(value))
                else:
                    value = str(sorted(list(value)))
            if test_total:
                value = value.replace('[', '[{}, '.format(test_total))
            if is_minimum:
                value = value + '**'
            elif is_small:
                value = value + '*'
            elif len(value)==0:
                value = np.NaN

            return value
        else:
            return value

    cols = set([int(v) for v in zip(*[c for c in df.columns])[1]])
    df = df.applymap(verify_test_value)

    return df

def index_mapper(meta, data, mapper, default=None, intersect=None):
    """
    Convert a {value: logic} map to a {value: index} map.

    This function takes a mapper of {key: logic} entries and resolves
    the logic statements using the given meta/data to return a mapper
    of {key: index}. The indexes returned can be used on data to isolate
    the cases described by arbitrarily complex logical statements.

    Parameters
    ----------
    meta : dict
        Quantipy meta document.
    data : pandas.DataFrame
        Data accompanying the given meta document.
    mapper : dict
        A mapper of {key: logic}
    default : str
        The column name to default to in cases where unattended lists
        are given as logic, where an auto-transformation of {key: list}
        to {key: {default: list}} is provided.

    Returns
    -------
    index_mapper : dict
        A mapper of {key: index}
    """

    if default is None:
        # Check that mapper isn't in a default-requiring
        # format
        for key, val in mapper.items():
            if not isinstance(val, (dict, tuple)):
                raise TypeError(
                    "'%s' recode definition appears to be using "
                    "default-shorthand but no value for 'default'"
                    "was given." % (key)
                )
        keyed_mapper = mapper
    else:
        # Use default to correct the form of the mapper
        # where un-keyed value lists were given
        # Creates: {value: {source: logic}}
        keyed_mapper = {
            key:
            {default: has_any(val)}
            if isinstance(val, list)
            else {default: val}
            for key, val in mapper.items()
        }

    # Apply any implied intersection
    if not intersect is None:
        keyed_mapper = {
            key: intersection([
                intersect,
                value if isinstance(value, dict) else {default: value}])
            for key, value in keyed_mapper.items()
        }

    # Create temp series with a full data index
    series = pd.Series(1, index=data.index)

    # Return indexes from logic statements
    # Creates: {value: index}
    index_mapper = {
        key: get_logic_index(series, logic, data)[0]
        for key, logic in keyed_mapper.items()
    }

    return index_mapper

def join_delimited_set_series(ds1, ds2, append=True):
    """
    Item-wise join of two delimited sets.

    This function takes a mapper of {key: logic} entries and resolves
    the logic statements using the given meta/data to return a mapper
    of {key: index}. The indexes returned can be used on data to isolate
    the cases described by arbitrarily complex logical statements.

    Parameters
    ----------
    ds1 : pandas.Series
        First delimited set series to join.
    ds2 : pandas.Series
        Second delimited set series to join.
    append : bool
        Should the data in ds2 (where found) be appended to items from
        ds1? If False, data from ds2 (where found) will overwrite
        whatever was found for that item in ds1 instead.

    Returns
    -------
    joined : pandas.Series
        The joined result of ds1 and ds2.
    """
    #import pdb; pdb.set_trace()
    if pd.__version__ == '0.19.2':
        df = pd.concat([ds1, ds2], axis=1, ignore_index=True)
    else:
        df = pd.concat([ds1, ds2], axis=1)
    df.fillna('', inplace=True)
    if append:
        df['joined'] = ds1 + ds2
    else:
        df['joined'] = ds1.copy()
        dfs2 = ds2.replace('', np.NaN)
        df['joined'].update(ds2.dropna())

    joined = df['joined'].replace('', np.NaN)
    return joined

def recode_from_index_mapper(meta, series, index_mapper, append):
    """
    Convert a {value: logic} map to a {value: index} map.

    This function takes a mapper of {key: logic} entries and resolves
    the logic statements using the given meta/data to return a mapper
    of {key: index}. The indexes returned can be used on data to isolate
    the cases described by arbitrarily complex logical statements.

    Parameters
    ----------
    meta : dict
        Quantipy meta document.
    series : pandas.Series
        The series in which the recoded data will be stored and
        returned.
    index_mapper : dict
        A mapper of {key: index}
    append : bool
        Should the new recodd data be appended to items already found
        in series? If False, data from series (where found) will
        overwrite whatever was found for that item in ds1 instead.

    Returns
    -------
    series : pandas.Series
        The series in which the recoded data will be stored and
        returned.
    """
    qtype = meta['columns'][series.name]['type']

    if qtype in ['delimited set']:
        if series.dtype in ['int64', 'float64']:
            not_null = series.notnull()
            if len(not_null) > 0:
                series.loc[not_null] = series.loc[not_null].map(str) + ';'
        if index_mapper:
            cols = [str(c) for c in sorted(index_mapper.keys())]
        else:
            vals = meta['columns'][series.name]['values']
            codes = [c['value'] for c in vals]
            cols = [str(c) for c in codes]
        ds = pd.DataFrame(0, index=series.index, columns=cols)
        for key, idx in index_mapper.items():
            ds[str(key)].loc[idx] = 1
        ds2 = condense_dichotomous_set(ds)
        org_name = series.name
        series = join_delimited_set_series(series, ds2, append)
        ## Remove potential duplicate values
        if series.dropna().empty:
            warn_msg = 'Could not recode {}, found empty data column dependency!'.format(org_name)
            warnings.warn(warn_msg)
            return series
        ds = series.str.get_dummies(';')
        # Make sure columns are in numeric order
        ds.columns = [int(float(c)) for c in ds.columns]
        cols = sorted(ds.columns.tolist())
        ds = ds[cols]
        ds.columns = [str(i) for i in ds.columns]
        # Reconstruct the dichotomous set
        series = condense_dichotomous_set(ds)

    elif qtype in ['single', 'int', 'float']:
        for key, idx in index_mapper.items():
            series.loc[idx] = key
    else:
        raise TypeError(
            "Can't recode '{col}'. Recoding for '{typ}' columns is not"
            " yet supported.".format(col=series.name, typ=qtype)
        )

    return series

def recode(meta, data, target, mapper, default=None, append=False,
           intersect=None, initialize=None, fillna=None):
    """
    Return a new or copied series from data, recoded using a mapper.

    This function takes a mapper of {key: logic} entries and injects the
    key into the target column where its paired logic is True. The logic
    may be arbitrarily complex and may refer to any other variable or
    variables in data. Where a pre-existing column has been used to
    start the recode, the injected values can replace or be appended to
    any data found there to begin with. Note that this function does
    not edit the target column, it returns a recoded copy of the target
    column. The recoded data will always comply with the column type
    indicated for the target column according to the meta.

    Parameters
    ----------
    meta : dict
        Quantipy meta document.
    data : pandas.DataFrame
        Data accompanying the given meta document.
    target : str
        The column name that is the target of the recode. If target
        is not found in meta['columns'] this will fail with an error.
        If target is not found in data.columns the recode will start
        from an empty series with the same index as data. If target
        is found in data.columns the recode will start from a copy
        of that column.
    mapper : dict
        A mapper of {key: logic} entries.
    default : str, default=None
        The column name to default to in cases where unattended lists
        are given in your logic, where an auto-transformation of
        {key: list} to {key: {default: list}} is provided. Note that
        lists in logical statements are themselves a form of shorthand
        and this will ultimately be interpreted as:
        {key: {default: has_any(list)}}.
    append : bool, default=False
        Should the new recodd data be appended to values already found
        in the series? If False, data from series (where found) will
        overwrite whatever was found for that item instead.
    intersect : logical statement, default=None
        If a logical statement is given here then it will be used as an
        implied intersection of all logical conditions given in the
        mapper.
    initialize : str or np.NaN, default=None
        If not None, a copy of the data named column will be used to
        populate the target column before the recode is performed.
        Alternatively, initialize can be used to populate the target
        column with np.NaNs (overwriting whatever may be there) prior
        to the recode.
    fillna : int, default=None
        If not None, the value passed to fillna will be used on the
        recoded series as per pandas.Series.fillna().

    Returns
    -------
    series : pandas.Series
        The series in which the recoded data is stored.
    """

    # Error handling
    # Check meta, data
    if not isinstance(meta, dict):
        raise ValueError("'meta' must be a dictionary.")
    if not isinstance(data, pd.DataFrame):
        raise ValueError("'data' must be a pandas.DataFrame.")

    # Check mapper
    if not isinstance(mapper, dict):
        raise ValueError("'mapper' must be a dictionary.")

    # Check target
    if not isinstance(target, str):
        raise ValueError("The value for 'target' must be a string.")
    if not target in meta['columns']:
        raise ValueError("'%s' not found in meta['columns']." % (target))

    # Check append
    if not isinstance(append, bool):
        raise ValueError("'append' must be boolean.")

    # Check column type vs append
    if append and meta['columns'][target]['type']!="delimited set":
        raise TypeError("'{}' is not a delimited set, cannot append.")

    # Check default
    if not default is None:
        if not isinstance(default, str):
            raise ValueError("The value for 'default' must be a string.")
        if not default in meta['columns']:
            raise ValueError("'%s' not found in meta['columns']." % (default))

    # Check initialize
    initialize_is_string = False
    if not initialize is None:
        if isinstance(initialize, str):
            initialize_is_string = True
            if not initialize in meta['columns']:
                raise ValueError("'%s' not found in meta['columns']." % (target))
        elif not np.isnan(initialize):
            raise ValueError(
                "The value for 'initialize' must either be"
                " a string naming an existing column or np.NaN.")

    # Resolve the logic to a mapper of {key: index}
    index_map = index_mapper(meta, data, mapper, default, intersect)

    # Get/create recode series
    if not initialize is None:
        if initialize_is_string:
            # Start from a copy of another existing column
            series = data[initialize].copy()
        else:
            # Ignore existing series for target, start with NaNs
            series = pd.Series(np.NaN, index=data.index, copy=True)
    elif target in data.columns:
        # Start with existing target column
        series = data[target].copy()
    else:
        # Start with NaNs
        series = pd.Series(np.NaN, index=data.index, copy=True)

    # Name the recoded series
    series.name = target

    # Use the index mapper to edit the target series
    series = recode_from_index_mapper(meta, series, index_map, append)

    # Rename the recoded series
    series.name = target

    if not fillna is None:
        col_type = meta['columns'][series.name]['type']
        if col_type=='single':
            series.fillna(fillna, inplace=True)
        elif col_type=='delimited set':
            series.fillna('{};'.format(fillna), inplace=True)

    return series

def merge_text_meta(left_text, right_text, overwrite=False):
    """
    Merge known text keys from right to left, add unknown text_keys.
    """
    if overwrite:
        left_text.update(right_text)
    else:
        for text_key in list(right_text.keys()):
            if not text_key in left_text:
                left_text[text_key] = right_text[text_key]

    return left_text

def merge_values_meta(left_values, right_values, overwrite=False):
    """
    Merge known left values from right to left, add unknown values.
    """
    for val_right in right_values:
        found = False
        for i, val_left in enumerate(left_values):
            if val_left['value']==val_right['value']:
                found = True
                left_values[i]['text'] = merge_text_meta(
                    val_left['text'],
                    val_right['text'],
                    overwrite=overwrite)
        if not found:
            left_values.append(val_right)

    return left_values

def merge_column_metadata(left_column, right_column, overwrite=False):
    """
    Merge the metadata from the right column into the left column.
    """
    _compatible_types(left_column, right_column)
    left_column['text'] = merge_text_meta(
            left_column['text'],
            right_column['text'],
            overwrite=overwrite)
    if 'values' in left_column and 'values' in right_column:
        left_column['values'] = merge_values_meta(
            left_column['values'],
            right_column['values'],
            overwrite=overwrite)
    return left_column

def _compatible_types(left_column, right_column):
    l_type = left_column['type']
    r_type = right_column['type']
    if l_type == r_type: return None
    all_types = ['array', 'int', 'float', 'single', 'delimited set', 'string',
                 'date', 'time', 'boolean']
    err = {
        'array': all_types,
        'int': [
            'float', 'delimited set', 'string', 'date', 'time', 'array'],
        'float': [
            'delimited set', 'string', 'date', 'time', 'array'],
        'single': all_types,
        'delimited set': [
            'string', 'date', 'time', 'array', 'int', 'float'],
        'string': [
            'int', 'float', 'single', 'delimited set', 'date', 'time', 'array'],
        'date': [
            'int', 'float', 'single', 'delimited set', 'string', 'time', 'array'],
        'time': [
            'int', 'float', 'single', 'delimited set', 'string', 'time', 'array'],
        }
    warn = {
        'int': [
            'single'],
        'float': [
            'int', 'single'],
        'delimited set': [
            'single'],
        'string': [
            'boolean']
    }
    if r_type in err.get(l_type, all_types):
        msg = "\n'{}': Trying to merge incompatibe types: Found '{}' in left "
        msg += "and '{}' in right dataset."
        raise TypeError(msg.format(left_column['name'], l_type, r_type))
    elif r_type in warn.get(l_type, all_types):
        msg = "\n'{}': Merge inconsistent types: Found '{}' in left "
        msg += "and '{}' in right dataset."
        warnings.warn(msg.format(left_column['name'], l_type, r_type))
    else:
        msg = "\n'{}': Found '{}' in left and '{}' in right dataset."
        raise TypeError(msg.format(left_column['name'], l_type, r_type))

def _update_mask_meta(left_meta, right_meta, masks, verbose, overwrite=False):
    """
    """
    # update mask
    if not isinstance(masks, list): masks = [masks]
    for mask in masks:
        old = left_meta['masks'][mask]
        new = right_meta['masks'][mask]
        for tk, t in list(new['text'].items()):
            if not tk in old['text'] or overwrite:
               old['text'].update({tk: t})
        for item in new['items']:
            check_source = item['source']
            check = 0
            for old_item in old['items']:
                if old_item['source'] == check_source:
                    check = 1
                    try:
                        for tk, t in list(item['text'].items()):
                            if not tk in old_item['text'] or overwrite:
                               old_item['text'].update({tk: t})
                    except:
                        if  verbose:
                            e = "'text' meta not valid for mask {}: item {}"
                            e = e.format(mask, item['source'].split('@')[-1])
                            print('{} - skipped!'.format(e))
                        else:
                            pass
            if check == 0:
                old['items'].append(item)
                # also add these items to ``meta['sets']``
                left_meta['sets'][mask]['items'].append(item['source'])


def merge_meta(meta_left, meta_right, from_set, overwrite_text=False,
               get_cols=False, get_updates=False, verbose=True):

    if verbose:
        print('\n', 'Merging meta...')

    if from_set is None:
        from_set = 'data file'

    # Find the columns to be merged
    if from_set in meta_right['sets']:
        if verbose:
            print(("New columns will be appended in the order found in"
                   " meta['sets']['{}'].".format(from_set)))

        cols = []
        masks = []
        mask_items = {}
        for item in meta_right['sets'][from_set]['items']:
            source, name = item.split('@')
            if source == 'columns':
                cols.append(name)
            elif source == 'masks':
                masks.append(name)
                for item in meta_right['masks'][name]['items']:
                    s, n = item['source'].split('@')
                    if s == 'columns':
                        cols.append(n)
                        if meta_right['masks'][name].get('values'):
                            mask_items[n] = 'lib@values@{}'.format(name)
        cols = uniquify_list(cols)

        if masks:
            for mask in masks:
                if not mask in meta_left['masks']:
                    if verbose:
                        print("Adding meta['masks']['{}']".format(mask))
                    meta_left['masks'][mask] = meta_right['masks'][mask]
                else:
                    _update_mask_meta(meta_left, meta_right, mask, verbose,
                                      overwrite=overwrite_text)

        sets = [key for key in meta_right['sets']
                if not key in meta_left['sets']]
        if sets:
            for set_name in sorted(sets):
                if verbose:
                    print("Adding meta['sets']['{}']".format(set_name))
                meta_left['sets'][set_name] = meta_right['sets'][set_name]

        for val in list(meta_right['lib']['values'].keys()):
            if not val in meta_left['lib']['values']:
                if verbose:
                    print("Adding meta['lib']['values']['{}']".format(val))
                meta_left['lib']['values'][val] = meta_right['lib']['values'][val]
            elif val == 'ddf' or (meta_left['lib']['values'][val] ==
                 meta_right['lib']['values'][val]):
                continue
            else:
                n_values = [v['value'] for v in meta_right['lib']['values'][val]]
                o_values = [v['value'] for v in meta_left['lib']['values'][val]]
                add_values = [v for v in n_values if v not in o_values]
                if add_values:
                    for value in meta_right['lib']['values'][val]:
                        if value['value'] in add_values:
                            meta_left['lib']['values'][val].append(value)

    else:
        if verbose:
            print((
                "No '{}' set was found, new columns will be appended"
                " alphanumerically.".format(from_set)
            ))
        cols = list(meta_right['columns'].keys()).sort(key=str.lower)

    col_updates = []
    for col_name in cols:
        if verbose:
            print('...', col_name)
        # store properties
        props = copy.deepcopy(
            meta_right['columns'][col_name].get('properties', {}))
        # emulate the right meta
        right_column = emulate_meta(
            meta_right,
            meta_right['columns'][col_name])
        if col_name in meta_left['columns'] and col_name in cols:
            col_updates.append(col_name)
            # emulate the left meta
            left_column = emulate_meta(
                meta_left,
                meta_left['columns'][col_name])
            # merge the eumlated metadata
            meta_left['columns'][col_name] = merge_column_metadata(
                left_column,
                right_column,
                overwrite=overwrite_text)
        else:
            # add metadata
            if right_column.get('properties'):
                right_column['properties']['merged'] = True
            else:
                right_column['properties'] = {'merged': True}

            meta_left['columns'][col_name] = right_column
        if 'properties' in meta_left['columns'][col_name]:
            meta_left['columns'][col_name]['properties'].update(props)
        if col_name in mask_items:
            meta_left['columns'][col_name]['values'] = mask_items[col_name]

    for item in meta_right['sets'][from_set]['items']:
        if not item in meta_left['sets']['data file']['items']:
            meta_left['sets']['data file']['items'].append(item)

    if get_cols and get_updates:
        return meta_left, cols, col_updates
    elif get_cols:
        return meta_left, cols
    elif get_updates:
        return meta_left, col_updates
    else:
        return meta_left

def get_columns_from_mask(meta, mask_name):
    """
    Recursively retrieve the columns indicated by the named mask.
    """

    cols = []
    for item in meta['masks'][mask_name]['items']:
        source, name = item['source'].split('@')
        if source=='columns':
            cols.append(name)
        elif source=='masks':
            cols.extend(get_columns_from_mask(meta, name))
        elif source=='sets':
            cols.extend(get_columns_from_set(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    return cols

def get_columns_from_set(meta, set_name):
    """
    Recursively retrieve the columns indicated by the named set.
    """

    cols = []
    for item in meta['sets'][set_name]['items']:
        source, name = item.split('@')
        if source=='columns':
            cols.append(name)
        elif source=='masks':
            cols.extend(get_columns_from_mask(meta, name))
        elif source=='sets':
            cols.extend(get_columns_from_set(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    cols = qp.core.tools.dp.query.uniquify_list(cols)

    return cols

def get_masks_from_mask(meta, mask_name):
    """
    Recursively retrieve the masks indicated by the named mask.
    """

    masks = []
    for item in meta['masks'][mask_name]['items']:
        source, name = item['source'].split('@')
        if source=='masks':
            masks.append(name)
        elif source=='columns':
            pass
        elif source=='sets':
            masks.extend(get_masks_from_set(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    return masks

def get_masks_from_set(meta, set_name):
    """
    Recursively retrieve the masks indicated by the named set.
    """

    masks = []
    for item in meta['sets'][set_name]['items']:
        source, name = item.split('@')
        if source=='masks':
            masks.append(name)
        elif source=='columns':
            pass
        elif source=='sets':
            masks.extend(get_masks_from_mask(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    return masks

def get_sets_from_mask(meta, mask_name):
    """
    Recursively retrieve the sets indicated by the named mask.
    """

    sets = []
    for item in meta['masks'][mask_name]['items']:
        source, name = item['source'].split('@')
        if source=='sets':
            sets.append(name)
        elif source=='columns':
            pass
        elif source=='masks':
            sets.extend(get_sets_from_mask(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    return sets

def get_sets_from_set(meta, set_name):
    """
    Recursively retrieve the sets indicated by the named set.
    """

    sets = []
    for item in meta['sets'][set_name]['items']:
        source, name = item.split('@')
        if source=='sets':
            sets.append(name)
        elif source=='columns':
            pass
        elif source=='masks':
            sets.extend(get_sets_from_mask(meta, name))
        else:
            raise KeyError(
                "Unsupported meta-mapping: {}".format(item))

    return sets

def hmerge(dataset_left, dataset_right, on=None, left_on=None, right_on=None,
           overwrite_text=False, from_set=None, merge_existing=None, verbose=True):
    """
    Merge Quantipy datasets together using an index-wise identifer.

    This function merges two Quantipy datasets (meta and data) together,
    updating variables that exist in the left dataset and appending
    others. New variables will be appended in the order indicated by
    the 'data file' set if found, otherwise they will be appended in
    alphanumeric order. This merge happend horizontally (column-wise).
    Packed kwargs will be passed on to the pandas.DataFrame.merge()
    method call, but that merge will always happen using how='left'.

    Parameters
    ----------
    dataset_left : tuple
        A tuple of the left dataset in the form (meta, data).
    dataset_right : tuple
        A tuple of the right dataset in the form (meta, data).
    on : str, default=None
        The column to use as a join key for both datasets.
    left_on : str, default=None
        The column to use as a join key for the left dataset.
    right_on : str, default=None
        The column to use as a join key for the right dataset.
    overwrite_text : bool, default=False
        If True, text_keys in the left meta that also exist in right
        meta will be overwritten instead of ignored.
    from_set : str, default=None
        Use a set defined in the right meta to control which columns are
        merged from the right dataset.
    merge_existing : str/ list of str, default None, {'all', [var_names]}
        Specify if codes should be merged for delimited sets for defined
        variables.
    verbose : bool, default=True
        Echo progress feedback to the output pane.

    Returns
    -------
    meta, data : dict, pandas.DataFrame
       Updated Quantipy dataset.
    """
    def _merge_delimited_sets(x):
        codes = []
        x = str(x).replace('nan', '')
        for c in x.split(';'):
            if not c:
                continue
            if not c in codes:
                codes.append(c)
        if not codes:
            return np.NaN
        else:
            return ';'.join(sorted(codes)) + ';'

    if all([kwarg is None for kwarg in [on, left_on, right_on]]):
        raise TypeError("You must provide a column name for either 'on' or "
                        "both 'left_on' AND 'right_on'")
    elif not on is None and not (left_on is None and right_on is None):
        raise ValueError("You cannot provide a value for both 'on' and either/"
                         "both 'left_on'/'right_on'.")
    elif on is None and (left_on is None or right_on is None):
        raise TypeError("You must provide a column name for both 'left_on' "
                        "AND 'right_on'")
    elif not on is None:
        left_on = on
        right_on = on

    meta_left = copy.deepcopy(dataset_left[0])
    data_left = dataset_left[1].copy()

    if isinstance(dataset_right, tuple): dataset_right = [dataset_right]
    for ds_right in dataset_right:
        meta_right = copy.deepcopy(ds_right[0])
        data_right = ds_right[1].copy()
        slicer = data_right[right_on].isin(data_left[left_on].values)
        data_right = data_right.loc[slicer, :]

        if verbose:
            print('\n', 'Checking metadata...')

        if from_set is None:
            from_set = 'data file'

        # Merge the right meta into the left meta
        meta_left, cols, col_updates = merge_meta(meta_left, meta_right,
                                                  from_set, overwrite_text,
                                                  True, True, verbose)

        # col_updates exception when left_on==right_on
        if left_on==right_on:
            col_updates.remove(left_on)
        if not left_on==right_on and right_on in col_updates:
            update_right_on = True
        else:
            update_right_on = False

        if verbose:
            print('\n', 'Merging data...')

        # update columns which are in left and in right data
        if col_updates:
            updata_left = data_left.copy()
            updata_left['org_idx'] = updata_left.index.tolist()
            updata_left = updata_left.set_index([left_on])[col_updates+['org_idx']]
            updata_right = data_right.set_index(
                right_on, drop=not update_right_on)[col_updates].copy()
            sets = [c for c in col_updates
                    if meta_left['columns'][c]['type'] == 'delimited set']
            non_sets = [c for c in col_updates if not c in sets]

            if verbose:
                print('------ updating data for known columns')
            updata_left.update(updata_right[non_sets])
            if merge_existing:
                for col in sets:
                    if not (merge_existing == 'all' or col in merge_existing):
                        continue
                    if verbose:
                        print("..{}".format(col))
                    updata_left[col] = updata_left[col].combine(
                        updata_right[col],
                        lambda x, y: _merge_delimited_sets(str(x)+str(y)))
            updata_left.reset_index(inplace=True)
            for col in col_updates:
                data_left[col] = updata_left[col].astype(data_left[col].dtype)

        # append completely new columns
        if verbose:
            print('------ appending new columns')
        new_cols = [col for col in cols if not col in col_updates]
        if update_right_on:
            new_cols.append(right_on)

        kwargs = {'left_on': left_on,
                  'right_on': right_on,
                  'how': 'left'}

        data_left = data_left.merge(data_right[new_cols], **kwargs)

        if update_right_on:
            new_cols.remove(right_on)
            _x = "{}_x".format(right_on)
            _y = "{}_y".format(right_on)
            data_left.rename(columns={_x: right_on}, inplace=True)
            data_left.drop(_y, axis=1, inplace=True)

        if verbose:
            for col_name in new_cols:
                print('..{}'.format(col_name))
            print('\n')

    return meta_left, data_left

def vmerge(dataset_left=None, dataset_right=None, datasets=None,
           on=None, left_on=None, right_on=None,
           row_id_name=None, left_id=None, right_id=None, row_ids=None,
           overwrite_text=False, from_set=None, reset_index=True,
           verbose=True):
    """
    Merge Quantipy datasets together by appending rows.

    This function merges two Quantipy datasets (meta and data) together,
    updating variables that exist in the left dataset and appending
    others. New variables will be appended in the order indicated by
    the 'data file' set if found, otherwise they will be appended in
    alphanumeric order. This merge happens vertically (row-wise).

    Parameters
    ----------
    dataset_left : tuple, default=None
        A tuple of the left dataset in the form (meta, data).
    dataset_right : tuple, default=None
        A tuple of the right dataset in the form (meta, data).
    datasets : list, default=None
        A list of datasets that will be iteratively sent into vmerge
        in pairs.
    on : str, default=None
        The column to use to identify unique rows in both datasets.
    left_on : str, default=None
        The column to use to identify unique in the left dataset.
    right_on : str, default=None
        The column to use to identify unique in the right dataset.
    row_id_name : str, default=None
        The named column will be filled with the ids indicated for each
        dataset, as per left_id/right_id/row_ids. If meta for the named
        column doesn't already exist a new column definition will be
        added and assigned a reductive-appropriate type.
    left_id : str/int/float, default=None
        Where the row_id_name column is not already populated for the
        dataset_left, this value will be populated.
    right_id : str/int/float, default=None
        Where the row_id_name column is not already populated for the
        dataset_right, this value will be populated.
    row_ids : list of str/int/float, default=None
        When datasets has been used, this list provides the row ids
        that will be populated in the row_id_name column for each of
        those datasets, respectively.
    overwrite_text : bool, default=False
        If True, text_keys in the left meta that also exist in right
        meta will be overwritten instead of ignored.
    from_set : str, default=None
        Use a set defined in the right meta to control which columns are
        merged from the right dataset.
    reset_index : bool, default=True
        If True pandas.DataFrame.reindex() will be applied to the merged
        dataframe.
    verbose : bool, default=True
        Echo progress feedback to the output pane.

    Returns
    -------
    meta, data : dict, pandas.DataFrame
        Updated Quantipy dataset.
    """

    if from_set is None:
        from_set = 'data file'

    if not datasets is None:
        if not isinstance(datasets, list):
            raise TypeError(
                "'datasets' must be a list.")
        if not datasets:
            raise ValueError(
                "'datasets' must be a populated list.")
        for dataset in datasets:
            if not isinstance(dataset, tuple):
                raise TypeError(
                    "The datasets in 'datasets' must be tuples.")
            if not len(dataset)==2:
                raise ValueError(
                    "The datasets in 'datasets' must be tuples with a"
                    " size of 2 (meta, data).")

        dataset_left = datasets[0]
        if row_ids:
            left_id = row_ids[0]
        for i in range(1, len(datasets)):
            dataset_right = datasets[i]
            if row_ids:
                right_id = row_ids[i]
            meta_vm, data_vm = vmerge(
                dataset_left, dataset_right,
                on=on, left_on=left_on, right_on=right_on,
                row_id_name=row_id_name, left_id=left_id, right_id=right_id,
                overwrite_text=overwrite_text, from_set=from_set,
                reset_index=reset_index,
                verbose=verbose)
            dataset_left = (meta_vm, data_vm)

        return meta_vm, data_vm

    if on is None and left_on is None and right_on is None:
        blind_append = True
    else:
        blind_append = False
        if on is None:
            if left_on is None or right_on is None:
                raise ValueError(
                    "You may not provide a value for only one of"
                    "'left_on'/'right_on'.")
        else:
            if not left_on is None or not right_on is None:
                raise ValueError(
                    "You cannot provide a value for both 'on' and either/"
                    "both 'left_on'/'right_on'.")
            left_on = on
            right_on = on

    meta_left = cpickle_copy(dataset_left[0])
    data_left = dataset_left[1].copy()

    if not blind_append:
        if not left_on in data_left.columns:
            raise KeyError(
                "'{}' not found in the left data.".format(left_on))
        if not left_on in meta_left['columns']:
            raise KeyError(
                "'{}' not found in the left meta.".format(left_on))

    meta_right = cpickle_copy(dataset_right[0])
    data_right = dataset_right[1].copy()

    if not blind_append:
        if not right_on in data_left.columns:
            raise KeyError(
                "'{}' not found in the right data.".format(right_on))
        if not right_on in meta_left['columns']:
            raise KeyError(
                "'{}' not found in the right meta.".format(right_on))

    if not row_id_name is None:
        if left_id is None and right_id is None:
            raise TypeError(
                "When indicating a 'row_id_name' you must also"
                " provide either 'left_id' or 'right_id'.")

        if row_id_name in meta_left['columns']:
            pass
            # text_key_right = meta_right['lib']['default text']
            # meta_left['columns'][row_id_name]['text'].update({
            #     text_key_right: 'vmerge row id'})
        else:
            left_id_int = isinstance(left_id, (int, np.int64))
            right_id_int = isinstance(right_id, (int, np.int64))
            if left_id_int and right_id_int:
                id_type = 'int'
            else:
                left_id_float = isinstance(left_id, (float, np.float64))
                right_id_float = isinstance(right_id, (float, np.float64))
                if (left_id_int or left_id_float) and (right_id_int or right_id_float):
                    id_type = 'float'
                    left_id = float(left_id)
                    right_id = float(right_id)
                else:
                    id_type = 'str'
                    left_id = str(left_id)
                    right_id = str(right_id)
            if verbose:
                print((
                    "'{}' was not found in the left meta so a new"
                    " column definition will be created for it. Based"
                    " on the given 'left_id' and 'right_id' types this"
                    " new column will be given the type '{}'.".format(
                        row_id_name,
                        id_type)))
            text_key_left = meta_left['lib']['default text']
            text_key_right = meta_right['lib']['default text']
            meta_left['columns'][row_id_name] = {
                'name': row_id_name,
                'type': id_type,
                'text': {
                    text_key_left: 'vmerge row id',
                    text_key_right: 'vmerge row id'}}
            id_mapper = "columns@{}".format(row_id_name)
            if not id_mapper in meta_left['sets']['data file']['items']:
                meta_left['sets']['data file']['items'].append(id_mapper)

        # Add the left and right id values
        if not left_id is None:
            if row_id_name in data_left.columns:
                left_id_rows = data_left[row_id_name].isnull()
                data_left.ix[left_id_rows, row_id_name] = left_id
            else:
                data_left[row_id_name] = left_id
        if not right_id is None:
            data_right[row_id_name] = right_id

    if verbose:
        print('\n', 'Checking metadata...')

    # Merge the right meta into the left meta
    meta_left, cols, col_updates = merge_meta(
        meta_left, meta_right,
        from_set=from_set,
        overwrite_text=overwrite_text,
        get_cols=True,
        get_updates=True,
        verbose=verbose)

    if not blind_append:
        vmerge_slicer = data_right[left_on].isin(data_left[right_on])
        data_right = data_right.loc[~vmerge_slicer]

    # convert right cols to delimited set if depending left col is delimited set
    for col in data_right.columns.tolist():
        if (meta_left['columns'].get(col, {}).get('type') == 'delimited set'
            and not meta_right['columns'][col]['type'] == 'delimited set'):
            data_right[col] = data_right[col].apply(
                lambda x: str(int(x)) + ';' if not np.isnan(x) else np.NaN)

    vdata = pd.concat([
        data_left,
        data_right
    ], sort=True)

    # Determine columns that should remain in the merged data
    cols_left = data_left.columns.tolist()

    col_slicer = cols_left + [
        col for col in get_columns_from_set(meta_right, from_set)
        if not col in cols_left]

    vdata = vdata[col_slicer]

    if reset_index:
        vdata.reset_index(drop=True, inplace=True)

    if verbose:
        print('\n')

    return meta_left, vdata

def subset_dataset(meta, data, columns):
    """
    Get a subset of the given meta
    """

    sdata = data[columns].copy()

    smeta = start_meta(text_key=meta['lib']['default text'])

    for col in columns:
        smeta['columns'][col] = meta['columns'][col]

    for col_mapper in meta['sets']['data file']['items']:
        if col_mapper.split('@')[-1] in columns:
            smeta['sets']['data file']['items'].append(col_mapper)

    return smeta, sdata
