"""Reads LMU's official shared memory ("LMU_Data"): driver names, and where the
player's settings are so the chat key can be looked up.

The layout mirrors Support\\SharedMemoryInterface in the LMU install
(SharedMemoryInterface.hpp and InternalsPlugin.hpp). Only the part up to the
vehicle scoring array is read. The game's lock is not taken, so we can never
stall it; instead a read is repeated until two copies agree.
"""
import ctypes
import json
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

MAP_NAME = "LMU_Data"
FILE_MAP_READ = 0x0004
MAX_VEHICLES = 104
SME_MAX = 16  # number of SharedMemoryEvent values
MAX_PATH = 260

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class TelemVect3(ctypes.Structure):
    _pack_ = 4
    _fields_ = (("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double))


class VehicleScoringInfoV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = (
        ("mID", ctypes.c_long),
        ("mDriverName", ctypes.c_char * 32),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTotalLaps", ctypes.c_short),
        ("mSector", ctypes.c_byte),
        ("mFinishStatus", ctypes.c_byte),
        ("mLapDist", ctypes.c_double),
        ("mPathLateral", ctypes.c_double),
        ("mTrackEdge", ctypes.c_double),
        ("mBestSector1", ctypes.c_double),
        ("mBestSector2", ctypes.c_double),
        ("mBestLapTime", ctypes.c_double),
        ("mLastSector1", ctypes.c_double),
        ("mLastSector2", ctypes.c_double),
        ("mLastLapTime", ctypes.c_double),
        ("mCurSector1", ctypes.c_double),
        ("mCurSector2", ctypes.c_double),
        ("mNumPitstops", ctypes.c_short),
        ("mNumPenalties", ctypes.c_short),
        ("mIsPlayer", ctypes.c_bool),
        ("mControl", ctypes.c_byte),
        ("mInPits", ctypes.c_bool),
        ("mPlace", ctypes.c_ubyte),
        ("mVehicleClass", ctypes.c_char * 32),
        ("mTimeBehindNext", ctypes.c_double),
        ("mLapsBehindNext", ctypes.c_long),
        ("mTimeBehindLeader", ctypes.c_double),
        ("mLapsBehindLeader", ctypes.c_long),
        ("mLapStartET", ctypes.c_double),
        ("mPos", TelemVect3),
        ("mLocalVel", TelemVect3),
        ("mLocalAccel", TelemVect3),
        ("mOri", TelemVect3 * 3),
        ("mLocalRot", TelemVect3),
        ("mLocalRotAccel", TelemVect3),
        ("mHeadlights", ctypes.c_ubyte),
        ("mPitState", ctypes.c_ubyte),
        ("mServerScored", ctypes.c_ubyte),
        ("mIndividualPhase", ctypes.c_ubyte),
        ("mQualification", ctypes.c_long),
        ("mTimeIntoLap", ctypes.c_double),
        ("mEstimatedLapTime", ctypes.c_double),
        ("mPitGroup", ctypes.c_char * 24),
        ("mFlag", ctypes.c_ubyte),
        ("mUnderYellow", ctypes.c_bool),
        ("mCountLapFlag", ctypes.c_ubyte),
        ("mInGarageStall", ctypes.c_bool),
        ("mUpgradePack", ctypes.c_ubyte * 16),
        ("mPitLapDist", ctypes.c_float),
        ("mBestLapSector1", ctypes.c_float),
        ("mBestLapSector2", ctypes.c_float),
        ("mSteamID", ctypes.c_ulonglong),
        ("mVehFilename", ctypes.c_char * 32),
        ("mAttackMode", ctypes.c_short),
        ("mFuelFraction", ctypes.c_ubyte),
        ("mDRSState", ctypes.c_bool),
        ("mExpansion", ctypes.c_ubyte * 4),
    )


class ScoringInfoV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = (
        ("mTrackName", ctypes.c_char * 64),
        ("mSession", ctypes.c_long),
        ("mCurrentET", ctypes.c_double),
        ("mEndET", ctypes.c_double),
        ("mMaxLaps", ctypes.c_long),
        ("mLapDist", ctypes.c_double),
        ("mResultsStream", ctypes.c_void_p),
        ("mNumVehicles", ctypes.c_long),
        ("mGamePhase", ctypes.c_ubyte),
        ("mYellowFlagState", ctypes.c_byte),
        ("mSectorFlag", ctypes.c_byte * 3),
        ("mStartLight", ctypes.c_ubyte),
        ("mNumRedLights", ctypes.c_ubyte),
        ("mInRealtime", ctypes.c_bool),
        ("mPlayerName", ctypes.c_char * 32),
        ("mPlrFileName", ctypes.c_char * 64),
        ("mDarkCloud", ctypes.c_double),
        ("mRaining", ctypes.c_double),
        ("mAmbientTemp", ctypes.c_double),
        ("mTrackTemp", ctypes.c_double),
        ("mWind", TelemVect3),
        ("mMinPathWetness", ctypes.c_double),
        ("mMaxPathWetness", ctypes.c_double),
        ("mGameMode", ctypes.c_ubyte),
        ("mIsPasswordProtected", ctypes.c_bool),
        ("mServerPort", ctypes.c_ushort),
        ("mServerPublicIP", ctypes.c_ulong),
        ("mMaxPlayers", ctypes.c_long),
        ("mServerName", ctypes.c_char * 32),
        ("mStartET", ctypes.c_float),
        ("mAvgPathWetness", ctypes.c_double),
        ("mSessionTimeRemaining", ctypes.c_float),
        ("mTimeOfDay", ctypes.c_float),
        ("mIsFixedSetup", ctypes.c_bool),
        ("mTrackGripLevel", ctypes.c_uint8),
        ("mCloudCoverage", ctypes.c_uint8),
        ("mTrackLimitsStepsPerPenalty", ctypes.c_uint8),
        ("mTrackLimitsStepsPerPoint", ctypes.c_uint8),
        ("mExpansion", ctypes.c_ubyte * 187),
        ("mVehicle", ctypes.c_void_p),  # pointer in the game's address space; unusable here
    )


class ApplicationStateV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = (
        ("mAppWindow", wintypes.HWND),
        ("mWidth", ctypes.c_ulong),
        ("mHeight", ctypes.c_ulong),
        ("mRefreshRate", ctypes.c_ulong),
        ("mWindowed", ctypes.c_ulong),
        ("mOptionsLocation", ctypes.c_ubyte),
        ("mOptionsPage", ctypes.c_char * 31),
        ("mExpansion", ctypes.c_ubyte * 204),
    )


# The structs below use default (natural) packing in the header.
class SharedMemoryGeneric(ctypes.Structure):
    _fields_ = (
        ("events", ctypes.c_uint32 * SME_MAX),
        ("gameVersion", ctypes.c_long),
        ("FFBTorque", ctypes.c_float),
        ("appInfo", ApplicationStateV01),
    )


class SharedMemoryPathData(ctypes.Structure):
    _fields_ = tuple((name, ctypes.c_char * MAX_PATH) for name in
                     ("userData", "customVariables", "stewardResults", "playerProfile", "pluginsFolder"))


class SharedMemoryHead(ctypes.Structure):
    """SharedMemoryObjectOut up to the end of scoring.vehScoringInfo."""
    _fields_ = (
        ("generic", SharedMemoryGeneric),
        ("paths", SharedMemoryPathData),
        ("scoringInfo", ScoringInfoV01),
        ("scoringStreamSize", ctypes.c_size_t),
        ("vehScoringInfo", VehicleScoringInfoV01 * MAX_VEHICLES),
    )


@dataclass
class Driver:
    name: str
    place: int
    lap_dist: float
    is_player: bool


@dataclass
class Session:
    track: str
    track_length: float
    drivers: list[Driver]


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").strip()


def _copy() -> SharedMemoryHead | None:
    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, MAP_NAME)
    if not handle:
        return None  # game not running, or a build without the interface
    try:
        view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, ctypes.sizeof(SharedMemoryHead))
        if not view:
            return None
        try:
            return SharedMemoryHead.from_buffer_copy(ctypes.string_at(view, ctypes.sizeof(SharedMemoryHead)))
        finally:
            kernel32.UnmapViewOfFile(view)
    finally:
        kernel32.CloseHandle(handle)


def _parse(head: SharedMemoryHead) -> Session:
    info = head.scoringInfo
    count = max(0, min(info.mNumVehicles, MAX_VEHICLES))
    drivers = [
        Driver(_text(v.mDriverName), v.mPlace, v.mLapDist, v.mIsPlayer)
        for v in head.vehScoringInfo[:count]
    ]
    return Session(_text(info.mTrackName), info.mLapDist, [d for d in drivers if d.name])


def read_session(attempts: int = 3) -> Session | None:
    """The current session, or None if LMU isn't running. Retries if the game was mid-write."""
    previous = None
    for _ in range(attempts):
        head = _copy()
        if head is None:
            return None
        session = _parse(head)
        if session == previous:
            return session
        previous = session
    return previous


def chat_key_scan() -> tuple[int, bool] | None:
    """LMU's "Realtime Chat" key as (scan code, extended), or None if LMU isn't
    running or the key isn't bound on the keyboard."""
    head = _copy()
    if head is None:
        return None
    profile = _text(head.paths.playerProfile)
    if not profile:
        return None
    try:
        bindings = json.loads((Path(profile) / "keyboard.json").read_text(encoding="utf-8"))
        code = int(bindings["Input"]["Realtime Chat"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if code <= 0:
        return None
    # DirectInput key codes: the 0x80 bit marks extended keys (numpad Enter, right Ctrl, arrows...).
    return code & 0x7F, bool(code & 0x80)


def names_nearest_first(session: Session) -> list[str]:
    """Other drivers' names, closest to the player around the lap first (by place if not driving)."""
    player = next((d for d in session.drivers if d.is_player), None)
    others = [d for d in session.drivers if not d.is_player]
    if player and session.track_length > 0:
        def gap(d: Driver) -> float:
            ahead = abs(d.lap_dist - player.lap_dist) % session.track_length
            return min(ahead, session.track_length - ahead)
        others.sort(key=gap)
    else:
        others.sort(key=lambda d: d.place)
    return list(dict.fromkeys(d.name for d in others))
