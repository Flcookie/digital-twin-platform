To deploy the dashboard correctly, ensure that all required files are stored within a single folder that also contains the "config.json" and "common.py files".

In the laboratory, connect to the network "THE FACTORY - ROUTER 3". Then, open the folder containing all the project files in PyCharm. Using the integrated terminal, run the following command: "python -m streamlit run main.py" .

Once executed, a new browser page will open. This serves as the main hub, from which you can navigate to and access all available dashboard pages. 

At this point, everything is ready. Verify that the connection to the broker has been successfully established using the indicator located in the top-right corner. As soon as the system starts generating and publishing data, the dashboard will automatically read it and update the pages.

Important: all the dashboards must be open before starting the system.

Please, initialize the system with all the pallets (according to the variabile "component_wips" in "config.json") placed at the input in corner2.

Examples of running dashboard are provided in folder "Examples_Running".