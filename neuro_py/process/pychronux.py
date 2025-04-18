from typing import List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.signal.windows import dpss


def getfgrid(Fs: int, nfft: int, fpass: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Get frequency grid for evaluation.

    Parameters
    ----------
    Fs : int
        Sampling frequency.
    nfft : int
        Number of points for FFT.
    fpass : List[float]
        Frequency range to evaluate (as [fmin, fmax]).

    Returns
    -------
    f : np.ndarray
        Frequency vector within the specified range.
    findx : np.ndarray
        Boolean array indicating the indices of the frequency vector that fall within the specified range.

    Notes
    -----
    The frequency vector is computed based on the sampling frequency and the number of FFT points.
    Only frequencies within the range defined by `fpass` are returned.
    """
    df = Fs / nfft
    f = np.arange(0, Fs + df, df)
    f = f[0:nfft]
    findx = (f >= fpass[0]) & (f <= fpass[-1])
    f = f[findx]
    return f, findx


def dpsschk(
    tapers: Union[np.ndarray, Tuple[float, int]], N: int, Fs: float
) -> np.ndarray:
    """
    Check and generate DPSS tapers.

    Parameters
    ----------
    tapers : Union[np.ndarray, Tuple[float, int]]
        Input can be either an array representing [NW, K] or a tuple with
        the number of tapers and the maximum number of tapers.
    N : int
        Number of points for FFT.
    Fs : float
        Sampling frequency.

    Returns
    -------
    tapers : np.ndarray
        Tapers matrix, shape [tapers, eigenvalues].

    Notes
    -----
    The function computes DPSS (Discrete Prolate Spheroidal Sequences) tapers
    and scales them by the square root of the sampling frequency.
    """
    tapers, eigs = dpss(N, NW=tapers[0], Kmax=tapers[1], sym=False, return_ratios=True)
    tapers = tapers * np.sqrt(Fs)
    tapers = tapers.T
    return tapers


def get_tapers(
    N: int,
    bandwidth: float,
    *,
    fs: float = 1.0,
    min_lambda: float = 0.95,
    n_tapers: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute tapers and associated energy concentrations for the Thomson
    multitaper method.

    Parameters
    ----------
    N : int
        Length of taper.
    bandwidth : float
        Bandwidth of taper, in Hz.
    fs : float, optional
        Sampling rate, in Hz. Default is 1 Hz.
    min_lambda : float, optional
        Minimum energy concentration that each taper must satisfy. Default is 0.95.
    n_tapers : Optional[int], optional
        Number of tapers to compute. Default is to use all tapers that satisfy 'min_lambda'.

    Returns
    -------
    tapers : np.ndarray
        Array of tapers with shape (n_tapers, N).
    lambdas : np.ndarray
        Energy concentrations for each taper with shape (n_tapers,).

    Raises
    ------
    ValueError
        If not enough tapers are available or if none of the tapers satisfy the
        minimum energy concentration criteria.
    """

    NW = bandwidth * N / fs
    K = int(np.ceil(2 * NW)) - 1
    if n_tapers is not None:
        K = min(K, n_tapers)
    if K < 1:
        raise ValueError(
            f"Not enough tapers, with 'NW' of {NW}. Increase the bandwidth or "
            "use more data points"
        )

    tapers, lambdas = dpss(N, NW=NW, Kmax=K, sym=False, norm=2, return_ratios=True)
    mask = lambdas > min_lambda
    if not np.sum(mask) > 0:
        raise ValueError(
            "None of the tapers satisfied the minimum energy concentration"
            f" criteria of {min_lambda}"
        )
    tapers = tapers[mask]
    lambdas = lambdas[mask]

    if n_tapers is not None:
        if n_tapers > tapers.shape[0]:
            raise ValueError(
                f"'n_tapers' of {n_tapers} is greater than the {tapers.shape[0]}"
                f" that satisfied the minimum energy concentration criteria of {min_lambda}"
            )
        tapers = tapers[:n_tapers]
        lambdas = lambdas[:n_tapers]

    return tapers, lambdas


def mtfftpt(
    data: np.ndarray,
    tapers: np.ndarray,
    nfft: int,
    t: np.ndarray,
    f: np.ndarray,
    findx: List[bool],
) -> Tuple[np.ndarray, float, float]:
    """
    Multitaper FFT for point process times.

    Parameters
    ----------
    data : np.ndarray
        1D array of spike times (in seconds).
    tapers : np.ndarray
        Tapers from the DPSS method.
    nfft : int
        Number of points for FFT.
    t : np.ndarray
        Time vector.
    f : np.ndarray
        Frequency vector.
    findx : list of bool
        Frequency index.

    Returns
    -------
    J : np.ndarray
        FFT of the data.
    Msp : float
        Mean spikes per time.
    Nsp : float
        Total number of spikes in data.

    Notes
    -----
    The function computes the multitaper FFT of spike times using
    the specified tapers and returns the FFT result, mean spikes,
    and total spike count.
    """
    K = tapers.shape[1]
    nfreq = len(f)

    # get the FFT of the tapers
    H = np.zeros((nfft, K), dtype=np.complex128)
    for i in np.arange(K):
        H[:, i] = np.fft.fft(tapers[:, i], nfft, axis=0)

    H = H[findx, :]
    w = 2 * np.pi * f
    dtmp = data
    indx = np.logical_and(dtmp >= np.min(t), dtmp <= np.max(t))
    if len(indx):
        dtmp = dtmp[indx]
    Nsp = len(dtmp)

    # get the mean spike rate
    Msp = Nsp / len(t)

    if Msp != 0:
        # Interpolate spike times for each taper
        data_proj = np.empty((len(dtmp), K))
        for i in range(K):
            data_proj[:, i] = np.interp(dtmp, t, tapers[:, i])

        def compute_J(k):
            J_k = np.zeros(nfreq, dtype=np.complex128)
            for i, freq in enumerate(w):
                phase = -1j * freq * (dtmp - t[0])
                J_k[i] = np.sum(np.exp(phase) * data_proj[:, k])
            return J_k

        J = np.array(Parallel(n_jobs=-1)(delayed(compute_J)(k) for k in range(K))).T

        J -= H * Msp
    else:
        # No spikes: return zeros
        J = np.zeros((nfreq, K), dtype=np.complex128)

    return J, Msp, Nsp


def mtspectrumpt(
    data: np.ndarray,
    Fs: int,
    fpass: list,
    NW: Union[int, float] = 2.5,
    n_tapers: int = 4,
    time_support: Union[list, None] = None,
    tapers: Union[np.ndarray, None] = None,
    tapers_ts: Union[np.ndarray, None] = None,
    nfft: Optional[int] = None,
) -> pd.DataFrame:
    """
    Multitaper power spectrum estimation for point process data.

    Parameters
    ----------
    data : np.ndarray
        Array of spike times (in seconds).
    Fs : int
        Sampling frequency.
    fpass : list of float
        Frequency range to evaluate.
    NW : Union[int, float], optional
        Time-bandwidth product (default is 2.5).
    n_tapers : int, optional
        Number of tapers (default is 4).
    time_support : Union[list, None], optional
        Time range to evaluate (default is None).
    tapers : Union[np.ndarray, None], optional
        Precomputed tapers, given as [NW, K] or [tapers, eigenvalues] (default is None).
    tapers_ts : Union[np.ndarray, None], optional
        Taper time series (default is None).
    nfft : Optional[int], optional
        Number of points for FFT (default is None).

    Returns
    -------
    pd.DataFrame
        DataFrame containing the power spectrum.


    Examples
    -------
    >>> spec = pychronux.mtspectrumpt(
    >>>    st.data,
    >>>    100,
    >>>    [1, 20],
    >>>    NW=3,
    >>>    n_tapers=5,
    >>>    time_support=[st.support.start, st.support.stop],
    >>>    nfft=500,
    >>> )
    """

    # check data
    if len(data) == 0:
        return pd.DataFrame()

    # check frequency range
    if fpass[0] > fpass[1]:
        raise ValueError(
            "Invalid frequency range: fpass[0] should be less than fpass[1]."
        )

    if time_support is not None:
        mintime, maxtime = time_support
    else:
        if data.dtype == np.object_:
            mintime = np.min(np.concatenate(data))
            maxtime = np.max(np.concatenate(data))
        else:
            mintime = np.min(data)
            maxtime = np.max(data)

    dt = 1 / Fs

    if tapers is None:
        tapers_ts = np.arange(mintime - dt, maxtime + dt, dt)
        N = len(tapers_ts)
        tapers, eigens = dpss(N, NW, n_tapers, return_ratios=True)
        tapers = tapers.T

    if tapers_ts is None:
        tapers_ts = np.arange(mintime - dt, maxtime + dt, dt)

    N = len(tapers_ts)
    # number of points in fft of prolates
    if nfft is None:
        nfft = np.max([int(2 ** np.ceil(np.log2(N))), N])
    f, findx = getfgrid(Fs, nfft, fpass)

    spec = np.zeros((len(f), len(data)))
    for i, d in enumerate(data):
        J, _, _ = mtfftpt(d, tapers, nfft, tapers_ts, f, findx)
        spec[:, i] = np.real(np.mean(np.conj(J) * J, 1))

    spectrum_df = pd.DataFrame(index=f, columns=np.arange(len(data)), dtype=np.float64)
    spectrum_df[:] = spec
    return spectrum_df


def mtfftc(data: np.ndarray, tapers: np.ndarray, nfft: int, Fs: int) -> np.ndarray:
    """
    Multi-taper Fourier Transform - Continuous Data (Single Signal)

    Parameters
    ----------
    data : np.ndarray
        1D array of data (samples).
    tapers : np.ndarray
        Precomputed DPSS tapers with shape (samples, tapers).
    nfft : int
        Length of padded data for FFT.
    Fs : int
        Sampling frequency.

    Returns
    -------
    J : np.ndarray
        FFT in the form (nfft, K), where K is the number of tapers.
    """
    # Ensure data is 1D
    if data.ndim != 1:
        raise ValueError("Input data must be a 1D array.")

    NC = data.shape[0]  # Number of samples in data
    NK, K = tapers.shape  # Number of samples and tapers

    if NK != NC:
        raise ValueError("Length of tapers is incompatible with length of data.")

    # Project data onto tapers
    data_proj = data[:, np.newaxis] * tapers  # Shape: (samples, tapers)

    # Compute FFT for each taper
    J = np.fft.fft(data_proj, n=nfft, axis=0) / Fs  # Shape: (nfft, K)

    return J


def mtspectrumc(
    data: np.ndarray, Fs: int, fpass: list, tapers: np.ndarray
) -> pd.Series:
    """
    Compute the multitaper power spectrum for continuous data.

    Parameters
    ----------
    data : np.ndarray
        1D array of continuous data (e.g., LFP).
    Fs : int
        Sampling frequency in Hz.
    fpass : list
        Frequency range to evaluate as [min_freq, max_freq].
    tapers : np.ndarray
        Tapers array with shape [NW, K] or [tapers, eigenvalues].

    Returns
    -------
    S : pd.Series
        Power spectrum with frequencies as the index.

    Notes
    -----
    This function utilizes the multitaper method for spectral estimation
    and returns the power spectrum as a pandas Series.
    """
    N = len(data)
    nfft = np.max(
        [int(2 ** np.ceil(np.log2(N))), N]
    )  # number of points in fft of prolates
    # get the frequency grid
    f, findx = getfgrid(Fs, nfft, fpass)
    # get the fft of the tapers
    tapers = dpsschk(tapers, N, Fs)
    # get the fft of the data
    J = mtfftc(data, tapers, nfft, Fs)
    # restrict fft of tapers to required frequencies
    J = J[findx, :]
    # get the power spectrum
    S = np.real(np.mean(np.conj(J) * J, 1))
    # return the power spectrum
    return pd.Series(index=f, data=S)


def point_spectra(
    times: np.ndarray,
    Fs: int = 1250,
    freq_range: List[float] = [1, 20],
    tapers0: List[int] = [3, 5],
    pad: int = 0,
    nfft: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute multitaper power spectrum for point processes.

    Parameters
    ----------
    times : np.ndarray
        Array of spike times (in seconds).
    Fs : int, optional
        Sampling frequency (default is 1250 Hz).
    freq_range : List[float], optional
        Frequency range to evaluate (default is [1, 20] Hz).
    tapers0 : List[int], optional
        Time-bandwidth product and number of tapers (default is [3, 5]).
        The time-bandwidth product is used to compute the tapers.
    pad : int, optional
        Padding for the FFT (default is 0).
    nfft : Optional[int], optional
        Number of points for FFT (default is None).

    Returns
    -------
    spectra : np.ndarray
        Power spectrum.
    f : np.ndarray
        Frequency vector.

    Notes
    -----
    Alternative function to `mtspectrumpt` for computing the power spectrum
    """

    # generate frequency grid
    timesRange = [min(times), max(times)]
    window = np.floor(np.diff(timesRange))
    nSamplesPerWindow = int(np.round(Fs * window[0]))
    if nfft is None:
        nfft = np.max(
            [(int(2 ** np.ceil(np.log2(nSamplesPerWindow))) + pad), nSamplesPerWindow]
        )
    fAll = np.linspace(0, Fs, int(nfft))
    frequency_ind = (fAll >= freq_range[0]) & (fAll <= freq_range[1])

    # Generate tapers
    tapers, _ = dpss(nSamplesPerWindow, tapers0[0], tapers0[1], return_ratios=True)
    tapers = tapers * np.sqrt(Fs)

    # Compute FFT of tapers and restrict to required frequencies
    H = np.fft.fft(tapers, n=nfft, axis=1)  # Shape: (K, nfft)
    H = H[:, frequency_ind]  # Shape: (K, Nf)

    # Angular frequencies
    f = fAll[frequency_ind]
    w = 2 * np.pi * f

    # Time grid
    timegrid = np.linspace(timesRange[0], timesRange[1], nSamplesPerWindow)

    # Ensure times are within range
    data = times[(times >= timegrid[0]) & (times <= timegrid[-1])]

    # Project spike times onto tapers
    data_proj = [np.interp(data, timegrid, taper) for taper in tapers]
    data_proj = np.vstack(data_proj)  # Shape: (K, len(data))

    # Compute multitaper spectrum
    exponential = np.exp(
        np.outer(-1j * w, (data - timegrid[0]))
    )  # Shape: (Nf, len(data))
    J = exponential @ data_proj.T - H.T * len(data) / len(timegrid)  # Shape: (Nf, K)
    spectra = np.squeeze(np.mean(np.real(np.conj(J) * J), axis=1))  # Mean across tapers

    return spectra, f


def mtcsdpt(
    data1: np.ndarray,
    data2: np.ndarray,
    Fs: int,
    fpass: list,
    NW: Union[int, float] = 2.5,
    n_tapers: int = 4,
    time_support: Union[list, None] = None,
    tapers: Union[np.ndarray, None] = None,
    tapers_ts: Union[np.ndarray, None] = None,
    nfft: Optional[int] = None,
) -> pd.DataFrame:
    """
    Multitaper cross-spectral density (CSD) for point processes.

    Parameters
    ----------
    data1 : np.ndarray
        Array of spike times for the first signal (in seconds).
    data2 : np.ndarray
        Array of spike times for the second signal (in seconds).
    Fs : int
        Sampling frequency.
    fpass : list
        Frequency range to evaluate as [min_freq, max_freq].
    NW : Union[int, float], optional
        Time-bandwidth product, by default 2.5.
    n_tapers : int, optional
        Number of tapers, by default 4.
    time_support : Union[list, None], optional
        Time range to evaluate, by default None.
    tapers : Union[np.ndarray, None], optional
        Precomputed tapers, given as [NW, K] or [tapers, eigenvalues], by default None.
    tapers_ts : Union[np.ndarray, None], optional
        Taper time series, by default None.
    nfft : Optional[int], optional
        Number of points for FFT, by default None.

    Returns
    -------
    pd.DataFrame
        Cross-spectral density between the two point processes.
    """
    if time_support is not None:
        mintime, maxtime = time_support
    else:
        mintime = min(np.min(data1), np.min(data2))
        maxtime = max(np.max(data1), np.max(data2))
    dt = 1 / Fs

    # Create tapers if not provided
    if tapers is None:
        tapers_ts = np.arange(mintime - dt, maxtime + dt, dt)
        N = len(tapers_ts)
        tapers, eigens = dpss(N, NW, n_tapers, return_ratios=True)

    tapers = tapers.T
    N = len(tapers_ts)

    # Number of points in FFT
    if nfft is None:
        nfft = np.max([int(2 ** np.ceil(np.log2(N))), N])
    f, findx = getfgrid(Fs, nfft, fpass)

    # Compute the multitaper Fourier transforms of both spike trains
    J1, Msp1, Nsp1 = mtfftpt(data1, tapers, nfft, tapers_ts, f, findx)
    J2, Msp2, Nsp2 = mtfftpt(data2, tapers, nfft, tapers_ts, f, findx)

    # Cross-spectral density: Sxy = mean(conjugate(J1) * J2)
    csd = np.real(np.mean(np.conj(J1) * J2, axis=1))

    csd_df = pd.DataFrame(index=f, data=csd, columns=["CSD"])
    return csd_df


def mtcoherencept(
    data1: np.ndarray,
    data2: np.ndarray,
    Fs: int,
    fpass: list,
    NW: Union[int, float] = 2.5,
    n_tapers: int = 4,
    time_support: Union[list, None] = None,
    tapers: Union[np.ndarray, None] = None,
    tapers_ts: Union[np.ndarray, None] = None,
    nfft: Optional[int] = None,
) -> pd.DataFrame:
    """
    Multitaper coherence for point processes.

    Parameters
    ----------
    data1 : np.ndarray
        Array of spike times for the first signal (in seconds).
    data2 : np.ndarray
        Array of spike times for the second signal (in seconds).
    Fs : int
        Sampling frequency.
    fpass : list
        Frequency range to evaluate as [min_freq, max_freq].
    NW : Union[int, float], optional
        Time-bandwidth product, by default 2.5.
    n_tapers : int, optional
        Number of tapers, by default 4.
    time_support : Union[list, None], optional
        Time range to evaluate, by default None.
    tapers : Union[np.ndarray, None], optional
        Precomputed tapers, given as [NW, K] or [tapers, eigenvalues], by default None.
    tapers_ts : Union[np.ndarray, None], optional
        Taper time series, by default None.
    nfft : Optional[int], optional
        Number of points for FFT, by default None.

    Returns
    -------
    pd.DataFrame
        Coherence between the two point processes.
    """
    # Check if data is a single unit and put in array
    if isinstance(data1, np.ndarray):
        data1 = np.array([data1])
    if isinstance(data2, np.ndarray):
        data2 = np.array([data2])

    # Compute power spectral densities (PSD) for both spike trains
    psd1 = mtspectrumpt(
        data1, Fs, fpass, NW, n_tapers, time_support, tapers, tapers_ts, nfft
    )
    psd2 = mtspectrumpt(
        data2, Fs, fpass, NW, n_tapers, time_support, tapers, tapers_ts, nfft
    )

    # Compute cross-spectral density (CSD) between the two spike trains
    csd = mtcsdpt(
        data1, data2, Fs, fpass, NW, n_tapers, time_support, tapers, tapers_ts, nfft
    )

    # Calculate coherence: |Sxy(f)|^2 / (Sxx(f) * Syy(f))
    coherence = np.abs(csd["CSD"].values) ** 2 / (psd1.values * psd2.values).flatten()

    # Return coherence as a pandas DataFrame
    coherence_df = pd.DataFrame(index=csd.index, data=coherence, columns=["Coherence"])
    return coherence_df
