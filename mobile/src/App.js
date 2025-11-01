import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import MangaListScreen from './screens/MangaListScreen';

const App = () => (
  <SafeAreaProvider>
    <StatusBar style="dark" />
    <MangaListScreen />
  </SafeAreaProvider>
);

export default App;
