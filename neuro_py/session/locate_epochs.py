__all__ = [
    "find_pre_task_post",
    "compress_repeated_epochs",
    "find_multitask_pre_post",
    "find_epoch_pattern",
]
import numpy as np
import pandas as pd

def find_pre_task_post(env, pre_post_label="sleep"):
    """
    given list of environment, finds first contigous epochs that meet pre/task/post

    Input:
        environment list, can be pandas column
    Output:
        indices of where pre-sleep/task/post-sleep exist

    example:
    pre_task_post = find_pre_task_post(epoch_df.environment)
    epoch_df.loc[pre_task_post]

            name	                        startTime	stopTime	environment
        1	OR15day1_sleep1_180116_110120	2001.600	8087.29195	sleep
        2	OR15day1_2_180116_171020	    8087.292	9952.05995	wmaze
        3	OR15day1_sleep2_180116_181618	9952.060	10182.92795	sleep
    """
    if len(env) < 3:
        return None, None
    numeric_idx = (pre_post_label == env) * 1
    dummy = np.zeros_like(numeric_idx) == 1
    if all(numeric_idx[:3] == [1, 0, 1]):
        dummy[:3] = True
        return dummy, [0, 1, 2]
    else:
        for i in np.arange(len(numeric_idx) + 3):
            if 3 + i > len(numeric_idx):
                return None, None
            if all(numeric_idx[0 + i : 3 + i] == [1, 0, 1]):
                dummy[0 + i : 3 + i] = True
                return dummy, [0, 1, 2] + i


def compress_repeated_epochs(epoch_df):
    """
    compress_repeated_epochs: Compresses epoch_df loaded by loading.load_epoch()
    If there are back to back epochs of the same name, it will combine them

    Input: epoch_df (uses: loading.load_epoch(basepath))
    Output: Compressed epoch_df

    Ryan H
    """
    match = np.zeros([epoch_df.environment.shape[0]])
    match[match == 0] = np.nan
    for i, ep in enumerate(epoch_df.environment[:-1]):
        if np.isnan(match[i]):
            # find match in current and next epoch
            if ep == epoch_df.environment.iloc[i + 1]:
                match[i : i + 2] = i
                # given match, see if there are more matches
                for match_i in np.arange(1, epoch_df.environment[:-1].shape[0]):
                    if i + 1 + match_i == epoch_df.environment.shape[0]:
                        break
                    if ep == epoch_df.environment.iloc[i + 1 + match_i]:

                        match[i : i + 1 + match_i + 1] = i
                    else:
                        break

    for i in range(len(match)):
        if np.isnan(match[i]):
            # make nans large numbers that are unlikely to be real epoch
            match[i] = (i + 1) * 2000

    # iter through each epoch indicator to get start and stop
    results = pd.DataFrame()
    no_nan_match = match[~np.isnan(match)]
    for m in pd.unique(no_nan_match):
        temp_dict = {}
        for item in epoch_df.keys():
            temp_dict[item] = epoch_df[match == m][item].iloc[0]

        temp_dict["startTime"] = epoch_df[match == m].startTime.min()
        temp_dict["stopTime"] = epoch_df[match == m].stopTime.max()

        temp_df = pd.DataFrame.from_dict(temp_dict, orient="index").T

        results = pd.concat([results, temp_df], ignore_index=True)
    return results


def find_multitask_pre_post(env, task_tag="open_field|linear_track|box|tmaze|wmaze"):
    """
    Find the row index for pre_task/post_task sleep for a given enviornment from cell explorer session.epochs dataframe
    Returns list of pre/task_post epochs for each task.
    input:
        df: data frame consisting of cell explorer session.epochs data
        col_name: name of column to query task tag. Default is environemnt
        task_tag: string within col_name that indicates a task.
    output:
        list of epoch indicies [pre_task, task, post_task] of size n = # of task epochs

    LB/RH 1/5/2022
    """
    # Find the row indices that contain the search string in the specified column
    task_bool = env.str.contains(task_tag, case=False)
    sleep_bool = env.str.contains("sleep", case=False)

    task_idx = np.where(task_bool)[0]
    task_idx = np.delete(task_idx, task_idx == 0, 0)
    sleep_idx = np.where(sleep_bool)[0]

    pre_task_post = []
    for task in task_idx:
        temp = sleep_idx - task
        pre_task = sleep_idx[temp < 0]
        post_task = sleep_idx[temp > 0]

        if len(post_task) == 0:
            print("no post_task sleep for task epoch " + str(task))
        elif len(pre_task) == 0:
            print("no pre_task sleep for task epoch " + str(task))
        else:
            pre_task_post.append([pre_task[-1], task, post_task[0]])

    if len(pre_task_post) == 0:
        pre_task_post = None

    return pre_task_post


def find_epoch_pattern(env, pattern):
    """
    given list of environment, finds contigous epochs that meet pattern

    Limitation: stops on the first instance of finding the pattern

    Input:
        env: environment list, can be pandas column
        pattern: pattern you are searching for
    Output:
        indices of where pattern exist

    example:
    epoch_df = loading.load_epoch(basepath)
    pattern_idx,_ = find_epoch_pattern(epoch_df.environment,['sleep','linear','sleep'])
    epoch_df.loc[pattern_idx]

        name	                startTime	stopTime	environment	behavioralParadigm	notes
    0	preSleep_210411_064951	0.0000	    9544.56315	sleep	    NaN	                NaN
    1	maze_210411_095201	    9544.5632	11752.80635	linear	    novel	            novel
    2	postSleep_210411_103522	11752.8064	23817.68955	sleep	    novel	            novel
    """

    env = list(env)
    pattern = list(pattern)

    if len(env) < len(pattern):
        return None, None

    dummy = np.zeros(len(env))

    for i in range(len(env) - len(pattern) + 1):
        if pattern == env[i : i + len(pattern)]:
            dummy[i : i + len(pattern)] = 1
            dummy = dummy == 1
            return dummy, np.arange(i, i + len(pattern))
    return None, None


def find_env_paradigm_pre_task_post(epoch_df, env="sleep", paradigm="memory"):
    """
    find_env_paradigm_pre_task_post: use env and paradigm to find pre task post
    Made because: FujisawaS data has Spontaneous alternation task & Working memory task
        both flanked by sleep. We want to locate the working memory task pre/task/post
    ex.

    >> epoch_df
        name	startTime	stopTime	environment	behavioralParadigm	            notes
    0	EE.042	0.0	        995.9384	sleep	    NaN	                            NaN
    1	EE.045	995.9384	3336.3928	tmaze	    Spontaneous alternation task	NaN
    2	EE.046	3336.3928	5722.444	sleep	    NaN	                            NaN
    3	EE.049	5722.444	7511.244	tmaze	    Working memory task	            NaN
    4	EE.050	7511.244	9387.644	sleep	    NaN	                            NaN

    >> idx = find_env_paradigm_pre_task_post(epoch_df)
    >> idx
    array([False, False,  True,  True,  True])

    """
    # compress back to back sleep epochs
    epoch_df_ = comp_rep_ep.main(epoch_df, epoch_name="sleep")
    # make col with env and paradigm
    epoch_df_["sleep_ind"] = (
        epoch_df_.environment + "_" + epoch_df_.behavioralParadigm.astype(str)
    )
    # locate env and paradigm of choice with this col
    epoch_df_["sleep_ind"] = epoch_df_["sleep_ind"].str.contains(env + "|" + paradigm)
    # the pattern we are looking for is all True

    # https://stackoverflow.com/questions/48710783/pandas-find-and-index-rows-that-match-row-sequence-pattern
    pat = np.asarray([True, True, True])
    N = len(pat)
    idx = (
        epoch_df_["sleep_ind"]
        .rolling(window=N, min_periods=N)
        .apply(lambda x: (x == pat).all())
        .mask(lambda x: x == 0)
        .bfill(limit=N - 1)
        .fillna(0)
        .astype(bool)
    ).values
    return idx