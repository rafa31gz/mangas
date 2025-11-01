import { useMemo } from 'react';
import { useNetworkState } from 'expo-network';

export const useConnectivity = () => {
  const netInfo = useNetworkState();

  const isOnline = useMemo(() => {
    if (!netInfo) return true;
    if (netInfo.isConnected === null || netInfo.isConnected === undefined) {
      return true;
    }
    if (netInfo.isInternetReachable === false) {
      return false;
    }
    return Boolean(netInfo.isConnected);
  }, [netInfo]);

  return {
    isOnline,
    netInfo,
  };
};
