import javafx.application.Application;
import javafx.scene.Scene;
import javafx.scene.web.WebView;
import javafx.stage.Stage;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;

public class Aplicacion extends Application {
    private static String serverUrl = "http://127.0.0.1:8000"; // URL por defecto

    public static void main(String[] args) {
        try {
            // 1. Ejecutar Host.py en segundo plano sin consola
            // Usamos "pythonw" en lugar de "python" para evitar la ventana de comandos en Windows
            ProcessBuilder pb = new ProcessBuilder("pythonw", "Host.py");
            
            // Le decimos a Java que ejecute el comando DENTRO de la carpeta HOST
            pb.directory(new File("HOST")); 
            pb.start();

            // 2. Esperar 1.5 segundos para dar tiempo a que el servidor inicie y escriba el archivo
            Thread.sleep(1500);

            // 3. Leer la IP generada en el archivo
            File ipFile = new File("HOST" + File.separator + "direccion_ip.txt");
            if (ipFile.exists()) {
                serverUrl = new String(Files.readAllBytes(ipFile.toPath())).trim();
            } else {
                System.out.println("No se encontró el archivo de IP, usando localhost.");
            }
        } catch (Exception e) {
            e.printStackTrace();
        }

        // 4. Iniciar la interfaz gráfica de JavaFX
        launch(args);
    }

    @Override
    public void start(Stage primaryStage) {
        // Crear el WebView y cargar la URL
        WebView webView = new WebView();
        webView.getEngine().load(serverUrl);

        // Configurar la ventana
        Scene scene = new Scene(webView, 1200, 800);
        primaryStage.setTitle("Danny's Glassworks");
        primaryStage.setScene(scene);
        
        // Al cerrar la ventana, terminar el proceso de Java
        primaryStage.setOnCloseRequest(event -> System.exit(0));
        
        primaryStage.show();
    }
}